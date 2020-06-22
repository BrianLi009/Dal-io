import numpy as np
import pandas as pd

from dalio.pipe import Pipe

from dalio.pipe.extra_classes import (
    _ColSelection, 
    _ColMapSelection, 
    _ColValSelection
)

from dalio.util import (
        out_of_place_col_insert,
        get_numeric_column_names,
        process_cols
)

from dalio.validator import HAS_LEVELS


class Bin(_ColMapSelection):
    """A pipeline stage that adds a binned version of a column or columns.

    If drop is set to True the new columns retain the names of the source
    columns; otherwise, the resulting column gain the suffix '_bin'

    Parameters
    ----------
    bin_map : dict
        Maps column labels to bin arrays. The bin array is interpreted as
        containing start points of consecutive bins, except for the final
        point, assumed to be the end point of the last bin. Additionally, a
        bin array implicitly projects a left-most bin containing all elements
        smaller than the left-most end point and a right-most bin containing
        all elements larger that the right-most end point. For example, the
        list [0, 5, 8] is interpreted as the bins (-∞, 0),
        [0-5), [5-8) and [8, ∞).
    drop : bool, default True
        If set to True, the source columns are dropped after being binned.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> df = pd.DataFrame([[-3],[4],[5], [9]], [1,2,3, 4], ['speed'])
        >>> pdp.Bin({'speed': [5]}, drop=False).apply(df)
           speed speed_bin
        1     -3        <5
        2      4        <5
        3      5        5≤
        4      9        5≤
        >>> pdp.Bin({'speed': [0,5,8]}, drop=False).apply(df)
           speed speed_bin
        1     -3        <0
        2      4       0-5
        3      5       5-8
        4      9        8≤
    """

    def __init__(self, bin_map, level=None, drop=True):
        super().__init__(bin_map, level=level)
        self._drop = drop

    def transform(self, data, **kwargs):

        inter_df = data.copy()
        _, levels = self._extract_col_names(data, filter_cols=False)

        for colname in self._cols:

            new_col = self._extract_col(inter_df, colname)\
                    .transform(pd.cut, axis=1, bins=(self._map_dict[colname]))

            if self._drop:
                self._insert_col(inter_df, new_col, colname)
            else:
                new_name = colname + "_bin"

                if self._level is not None:
                    levels[self._level] = [new_name]
                    new_col.columns = pd.MultiIndex.from_product(
                        list(levels.values()))
                else:
                    new_col.colname = new_name

                inter_df = self._add_col(inter_df, new_col)

        return inter_df


class OneHotEncode(_ColSelection):
    """A pipeline stage that one-hot-encodes categorical columns.

    By default only k-1 dummies are created fo k categorical levels, as to
    avoid perfect multicollinearity between the dummy features (also called
    the dummy variabletrap). This is done since features are usually one-hot
    encoded for use with linear models, which require this behaviour.

    Parameters
    ----------
    columns : single label or list-like, default None
        Column labels in the DataFrame to be encoded. If columns is None then
        all the columns with object or category dtype will be converted, except
        those given in the exclude_columns parameter.
    dummy_na : bool, default False
        Add a column to indicate NaNs, if False NaNs are ignored.
    exclude_columns : str or list-like, default None
        Name or names of categorical columns to be excluded from encoding
        when the columns parameter is not given. If None no column is excluded.
        Ignored if the columns parameter is given.
    col_subset : bool, default False
        If set to True, and only a subset of given columns is found, they are
        encoded (if the missing columns are encoutered after the stage is
        fitted they will be ignored). Otherwise, the stage will fail on the
        precondition requiring all given columns are in input dataframes.
    drop_first : bool or single label, default True
        Whether to get k-1 dummies out of k categorical levels by removing the
        first level. If a non bool argument matching one of the categories is
        provided, the dummy column corresponding to this value is dropped
        instead of the first level; if it matches no category the first
        category will still be dropped.
    drop : bool, default True
        If set to True, the source columns are dropped after being encoded.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> df = pd.DataFrame([['USA'], ['UK'], ['Greece']], [1,2,3], ['Born'])
        >>> pdp.OneHotEncode().apply(df)
           Born_UK  Born_USA
        1        0         1
        2        1         0
        3        0         0
    """

    class _FitterEncoder:
        def __init__(self, col_name, dummy_columns):
            self.col_name = col_name
            self.dummy_columns = dummy_columns

        def __call__(self, value):
            this_dummy = "{}_{}".format(self.col_name, value)
            return pd.Series(
                data=[
                    int(this_dummy == dummy_col)
                    for dummy_col in self.dummy_columns
                ],
                index=self.dummy_columns,
            )

    def __init__(
        self,
        columns=None,
        level=None,
        dummy_na=False,
        exclude_columns=None,
        col_subset=False,
        drop_first=True,
        drop=True,
        **kwargs
    ):
        super().__init__(columns, level=level)

        if self._level is not None:
            # this operation will change datafram shapes, which means that it
            # can only be performed on the last level of an index
            self._source\
                .add_desc(HAS_LEVELS(level, axis=1, comparisson="=="))

        self._dummy_na = dummy_na

        if exclude_columns is None:
            self._exclude_columns = []
        else:
            self._exclude_columns = process_cols(exclude_columns)

        self._col_subset = col_subset
        self._drop_first = drop_first
        self._drop = drop

    def transform(self, data, **kwargs):

        inter_df = data.copy()

        columns_to_encode, levels = \
            self._extract_col_names(data, filter_cols=False)
        
        # TODO: standardize exclusion mechanics
        if self._cols is None:
            columns_to_encode = list(
                set(
                    data.select_dtypes(include=["object", "category"]).columns
                ).difference(self._exclude_columns)
            )

        if self._col_subset:
            columns_to_encode = [
                x for x in columns_to_encode if x in data.columns
            ]

        for colname in columns_to_encode:

            new_col = pd.get_dummies(
                self._extract_col(inter_df, colname),
                columns=colname,
                drop_first=self._drop_first,
                dummy_na=self._dummy_na,
                prefix=colname,
                prefix_sep="_",
            )

            if self._drop:
                self._insert_col(inter_df, new_col, colname)
            else:
                new_name = colname + "_dummy"

                if self._level is not None:
                    levels[self._level] = [new_name]
                    new_col.columns = pd.MultiIndex.from_product(
                        list(levels.values()))
                else:
                    new_col.colname = new_name

                inter_df = self._add_col(inter_df, new_col)

        return inter_df


class MapColVals(_ColValSelection):
    """A pipeline stage that replaces the values of a column by a map.

    Parameters
    ----------
    columns : single label or list-like
        Column labels in the DataFrame to be mapped.
    value_map : dict, function or pandas.Series
        A dictionary mapping existing values to new ones. Values not in the
        dictionary as keys will be converted to NaN. If a function is given, it
        is applied element-wise to given columns. If a Series is given, values
        are mapped by its index to its values.
    result_columns : single label or list-like, default None
        Labels for the new columns resulting from the mapping operation. Must
        be of the same length as columns. If None, behavior depends on the
        drop parameter: If drop is True, then the label of the source column is
        used; otherwise, the label of the source column is used with the suffix
        '_map'.
    drop : bool, default True
        If set to True, source columns are dropped after being mapped.
    suffix : str, default '_map'
        The suffix mapped columns gain if no new column labels are given.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> df = pd.DataFrame([[1], [3], [2]], ['UK', 'USSR', 'US'], ['Medal'])
        >>> value_map = {1: 'Gold', 2: 'Silver', 3: 'Bronze'}
        >>> pdp.MapColVals('Medal', value_map).apply(df)
               Medal
        UK      Gold
        USSR  Bronze
        US    Silver
    """

    def __init__(
        self,
        columns,
        value_map,
        result_columns=None,
        drop=True,
        suffix=None,
    ):
        super().__init__(columns, value_map)

        if suffix is None:
            suffix = "_map"
        self.suffix = suffix

        if result_columns is None:
            if drop:
                self._result_columns = self._cols
            else:
                self._result_columns = [
                    col + self.suffix for col in self._cols
                ]
        else:
            self._result_columns = process_cols(result_columns)
            if len(self._result_columns) != len(self._cols):
                raise ValueError(
                    "columns and result_columns parameters must"
                    " be string lists of the same length!"
                )

        self._drop = drop

    def transform(self, data, verbose):

        inter_df = data.copy()
        _, levels = self._extract_col_names(data, filter_cols=False)

        for colname in self._cols:

            new_col = self._extract_col(inter_df, colname)\
                    .transform(lambda x: x.map(self._values), axis=1)

            if self._drop:
                self._insert_col(inter_df, new_col, colname)
            else:
                new_name = colname + "_map"

                if self._level is not None:
                    levels[self._level] = [new_name]
                    new_col.columns = pd.MultiIndex.from_product(
                        list(levels.values()))
                else:
                    new_col.colname = new_name

                inter_df = self._add_col(inter_df, new_col)

        return inter_df

class ApplyToRows(Pipe):
    """A pipeline stage generating columns by applying a function to each row.

    Parameters
    ----------
    func : function
        The function to be applied to each row of the processed DataFrame.
    colname : single label, default None
        The label of the new column resulting from the function application. If
        None, 'new_col' is used. Ignored if a DataFrame is generated by the
        function (i.e. each row generates a Series rather than a value), in
        which case the laebl of each column in the resulting DataFrame is used.
    follow_column : str, default None
        Resulting columns will be inserted after this column. If None, new
        columns are inserted at the end of the processed DataFrame.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> data = [[3, 2143], [10, 1321], [7, 1255]]
        >>> df = pd.DataFrame(data, [1,2,3], ['years', 'avg_revenue'])
        >>> total_rev = lambda row: row['years'] * row['avg_revenue']
        >>> add_total_rev = pdp.ApplyToRows(total_rev, 'total_revenue')
        >>> add_total_rev(df)
           years  avg_revenue  total_revenue
        1      3         2143           6429
        2     10         1321          13210
        3      7         1255           8785
        >>> def halfer(row):
        ...     new = {'year/2': row['years']/2, 'rev/2': row['avg_revenue']/2}
        ...     return pd.Series(new)
        >>> half_cols = pdp.ApplyToRows(halfer, follow_column='years')
        >>> half_cols(df)
           years   rev/2  year/2  avg_revenue
        1      3  1071.5     1.5         2143
        2     10   660.5     5.0         1321
        3      7   627.5     3.5         1255
    """

    def __init__(
        self,
        func,
        colname=None,
        follow_column=None,
        **kwargs
    ):
        super().__init__()

        self._func = func
        self._colname = colname if colname is not None else "new_col"
        self._follow_column = follow_column

    def transform(self, data, **kwargs):

        new_cols = data.apply(self._func, axis=1)

        if isinstance(new_cols, pd.Series):
            loc = len(data.columns)

            if self._follow_column:
                loc = data.columns.get_loc(self._follow_column) + 1

            return out_of_place_col_insert(
                df=data,
                series=new_cols,
                loc=loc,
                column_name=self._colname
            )

        elif isinstance(new_cols, pd.DataFrame):

            sorted_cols = sorted(list(new_cols.columns))
            new_cols = new_cols[sorted_cols]

            if self._follow_column:

                inter_df = data
                loc = data.columns.get_loc(self._follow_column) + 1

                for colname in new_cols.columns:
                    inter_df = out_of_place_col_insert(
                        df=inter_df,
                        series=new_cols[colname],
                        loc=loc,
                        column_name=colname,
                    )
                    loc += 1

                return inter_df

            assign_map = {
                colname: new_cols[colname] for colname in new_cols.columns
            }

            return data.assign(**assign_map)

        raise TypeError(  # pragma: no cover
            "Unexpected type generated by applying a function to a DataFrame."
            " Only Series and DataFrame are allowed."
        )


class ApplyByCols(_ColSelection):
    """A pipeline stage applying an element-wise function to columns.

    Parameters
    ----------
    columns : str or list-like
        Names of columns on which to apply the given function.
    func : function
        The function to be applied to each element of the given columns.
    result_columns : str or list-like, default None
        The names of the new columns resulting from the mapping operation. Must
        be of the same length as columns. If None, behavior depends on the
        drop parameter: If drop is True, the name of the source column is used;
        otherwise, the name of the source column is used with the suffix
        '_app'.
    drop : bool, default True
        If set to True, source columns are dropped after being mapped.
    func_desc : str, default None
        A function description of the given function; e.g. 'normalizing revenue
        by company size'. A default description is used if None is given.


    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp; import math;
        >>> data = [[3.2, "acd"], [7.2, "alk"], [12.1, "alk"]]
        >>> df = pd.DataFrame(data, [1,2,3], ["ph","lbl"])
        >>> round_ph = pdp.ApplyByCols("ph", math.ceil)
        >>> round_ph(df)
           ph  lbl
        1   4  acd
        2   8  alk
        3  13  alk
    """

    def __init__(
        self,
        columns,
        func,
        result_columns=None,
        drop=True,
        **kwargs
    ):
        super().__init__(columns)

        self._func = func

        if result_columns is None:
            if drop:
                self._result_columns = self._cols
            else:
                self._result_columns = [col + "_app" for col in self._cols]
        else:
            self._result_columns = process_cols(result_columns)

            if len(self._result_columns) != len(self._cols):
                raise ValueError(
                    "columns and result_columns parameters must"
                    " be string lists of the same length!"
                )

        self._drop = drop

    def transform(self, data, **kwargs):

        inter_df = data

        for i, colname in enumerate(self._cols):

            source_col = data[colname]
            loc = data.columns.get_loc(colname) + 1
            new_name = self._result_columns[i]

            if self._drop:
                inter_df = inter_df.drop(colname, axis=1)
                loc -= 1

            inter_df = out_of_place_col_insert(
                df=inter_df,
                series=source_col.apply(self._func),
                loc=loc,
                column_name=new_name,
            )

        return inter_df


class ColByFrameFunc(Pipe):
    """A pipeline stage adding a column by applying a dataframw-wide function.

    Parameters
    ----------
    column : str
        The name of the resulting column.
    func : function
        The function to be applied to the input dataframe. The function should
        return a pandas.Series object.
    follow_column : str, default None
        Resulting columns will be inserted after this column. If None, new
        columns are inserted at the end of the processed DataFrame.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> data = [[3, 3], [2, 4], [1, 5]]
        >>> df = pd.DataFrame(data, [1,2,3], ["A","B"])
        >>> func = lambda df: df['A'] == df['B']
        >>> add_equal = pdp.ColByFrameFunc("A==B", func)
        >>> add_equal(df)
           A  B   A==B
        1  3  3   True
        2  2  4  False
        3  1  5  False
    """

    def __init__(
        self,
        column,
        func,
        follow_column=None,
        **kwargs
    ):
        super().__init__()
        self._cols = column

        self._func = func
        self._follow_column = follow_column

    def transform(self, data, **kwargs):
        inter_df = data

        try:
            new_col = self._func(data)
        except Exception:
            raise RuntimeError(
                "Exception raised applying function{} to dataframe.".format(
                    self._func_desc
                )
            )

        if self._follow_column:
            loc = data.columns.get_loc(self._follow_column) + 1
        else:
            loc = len(data.columns)

        inter_df = out_of_place_col_insert(
            df=inter_df,
            series=new_col,
            loc=loc,
            column_name=self._column
        )

        return inter_df


class AggByCols(_ColSelection):
    """A pipeline stage applying a series-wise function to columns.

    Parameters
    ----------
    columns : str or list-like
        Names of columns on which to apply the given function.
    func : function
        The function to be applied to each element of the given columns.
    result_columns : str or list-like, default None
        The names of the new columns resulting from the mapping operation. Must
        be of the same length as columns. If None, behavior depends on the
        drop parameter: If drop is True, the name of the source column is used;
        otherwise, the name of the source column is used with a defined suffix.
    drop : bool, default True
        If set to True, source columns are dropped after being mapped.
    func_desc : str, default None
        A function description of the given function; e.g. 'normalizing revenue
        by company size'. A default description is used if None is given.
    suffix : str, optional
        The suffix to add to resulting columns in case where results_columns
        is None and drop is set to False. Of not given, defaults to '_agg'.


    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp; import numpy as np;
        >>> data = [[3.2, "acd"], [7.2, "alk"], [12.1, "alk"]]
        >>> df = pd.DataFrame(data, [1,2,3], ["ph","lbl"])
        >>> log_ph = pdp.ApplyByCols("ph", np.log)
        >>> log_ph(df)
                 ph  lbl
        1  1.163151  acd
        2  1.974081  alk
        3  2.493205  alk
    """

    def __init__(
        self,
        columns,
        func,
        result_columns=None,
        drop=True,
        suffix=None,
        **kwargs
    ):
        super.__init__(columns)
        # TODO: deal with simplifying suffix additions
        self._suffix = suffix if suffix is not None else "_agg"
        self._func = func

        if result_columns is None:
            if drop:
                self._result_columns = self._cols
            else:
                self._result_columns = [col + suffix for col in self._cols]
        else:
            self._result_columns = process_cols(result_columns)
            if len(self._result_columns) != len(self._cols):
                raise ValueError(
                    "columns and result_columns parameters must"
                    " be string lists of the same length!"
                )

        self._drop = drop

    def transform(self, data, **kwargs):

        inter_df = data

        for i, colname in enumerate(self._cols):

            source_col = data[colname]
            loc = data.columns.get_loc(colname) + 1
            new_name = self._result_columns[i]

            if self._drop:
                inter_df = inter_df.drop(colname, axis=1)
                loc -= 1

            inter_df = out_of_place_col_insert(
                df=inter_df,
                series=source_col.agg(self._func),
                loc=loc,
                column_name=new_name,
            )

        return inter_df


class Log(_ColSelection):
    """A pipeline stage that log-transforms numeric data.

    Parameters
    ----------
    columns : str or list-like, default None
        Column names in the DataFrame to be encoded. If columns is None then
        all the columns with a numeric dtype will be transformed, except those
        given in the exclude_columns parameter.
    exclude : str or list-like, default None
        Name or names of numeric columns to be excluded from log-transforming
        when the columns parameter is not given. If None no column is excluded.
        Ignored if the columns parameter is given.
    drop : bool, default False
        If set to True, the source columns are dropped after being encoded,
        and the resulting encoded columns retain the names of the source
        columns. Otherwise, encoded columns gain the suffix '_log'.
    non_neg : bool, default False
        If True, each transformed column is first shifted by smallest negative
        value it includes (non-negative columns are thus not shifted).
    const_shift : int, optional
        If given, each transformed column is first shifted by this constant. If
        non_neg is True then that transformation is applied first, and only
        then is the column shifted by this constant.

    Example
    -------
        >>> import pandas as pd; import pdpipe as pdp;
        >>> data = [[3.2, "acd"], [7.2, "alk"], [12.1, "alk"]]
        >>> df = pd.DataFrame(data, [1,2,3], ["ph","lbl"])
        >>> log_stage = pdp.Log("ph", drop=True)
        >>> log_stage(df)
                 ph  lbl
        1  1.163151  acd
        2  1.974081  alk
        3  2.493205  alk
    """

    def __init__(
        self,
        columns=None,
        exclude=None,
        drop=False,
        non_neg=False,
        const_shift=None,
        **kwargs
    ):
        super().__init__(columns)

        self._exclude = process_cols(exclude) if exclude is not None else []
        self._drop = drop
        self._non_neg = non_neg
        self._const_shift = const_shift
        self._col_to_minval = {}

    def transform(self, data, **kwargs):
        columns_to_transform = self._cols

        if self._cols is None:
            columns_to_transform = get_numeric_column_names(data)

        columns_to_transform = list(
            set(columns_to_transform).difference(self._exclude)
        )

        inter_df = data

        for colname in columns_to_transform:

            source_col = data[colname]
            loc = data.columns.get_loc(colname) + 1
            new_name = colname + "_log"

            if self._drop:
                inter_df = inter_df.drop(colname, axis=1)
                new_name = colname
                loc -= 1

            new_col = source_col

            if self._non_neg:
                minval = min(new_col)
                if minval < 0:
                    new_col = new_col + abs(minval)
                    self._col_to_minval[colname] = abs(minval)

            # must check not None as neg numbers eval to False
            if self._const_shift is not None:
                new_col = new_col + self._const_shift

            new_col = np.log(new_col)

            inter_df = out_of_place_col_insert(
                df=inter_df,
                series=new_col,
                loc=loc,
                column_name=new_name
            )

        return inter_df

# TODO create copy functions
# TODO create better _ColSelection subclasses and simplify initialization
# of these
# TODO exclude fitting attributes
# TODO simplify transformation processes (many repeated steps as it is)
