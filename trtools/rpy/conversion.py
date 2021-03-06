import sys, copy, os, itertools
import time

import rpy2.robjects as robjects
import rpy2.rinterface as rinterface
from rpy2.robjects.vectors import SexpVector, ListVector, StrSexpVector
from rpy2.robjects.robject import RObjectMixin, RObject
import numpy as np
import pandas.rpy.common as rcom
import pandas as pd

NA_TYPES = rcom.NA_TYPES
VECTOR_TYPES = rcom.VECTOR_TYPES

baseenv_ri = rinterface.baseenv
globalenv_ri = rinterface.globalenv

# Probably need better logic to detect if xts was imported
robjects.r('require(xts)')

def pd_ri2py(o):
    res = None
    try:
        rcls = o.do_slot("class")
    except LookupError, le:
        rcls = [None]

    if isinstance(o, SexpVector):
        if 'xts' in rcls:
            print 'xts'
            res = convert_xts_to_df(o)
        if 'POSIXct' in rcls:
            res = convert_posixct_to_index(o)

    if res is None:
        res = robjects.default_ri2py(o)

    return res

def convert_xts_to_df(o):
    """
        Will convert xts objects to DataFrame
    """
    dates = o.do_slot('index')
    dates = np.array(dates, dtype=np.dtype("M8[s]"))
    res = robjects.default_ri2py(o)
    df = rcom.convert_robj(res)
    df.index = dates
    return df

def convert_posixct_to_index(o):
    """
        Convert a POSIXct object to a DatetimeIndex.
    """
    tz = o.do_slot('tzone')[0]
    dates = np.array(o, dtype=np.dtype("M8[s]"))
    index = pd.DatetimeIndex(dates, tz='UTC')
    index = index.tz_convert(tz)
    return index

robjects.conversion.ri2py = pd_ri2py

def pd_py2ri(o):
    """ 
    """
    res = None
    if isinstance(o, pd.DataFrame): 
        if isinstance(o.index, pd.DatetimeIndex):
            res = convert_df_to_xts(o)
        else:
            res = rcom.convert_to_r_dataframe(o)

    if isinstance(o, pd.DatetimeIndex): 
        res = convert_datetime_index(o)
        
    if res is None:
        res = robjects.default_py2ri(o)

    return res

def convert_dataframe_columns(df, strings_as_factors=False):
    """
    Essentially the same as pandas.spy.common.convert_to_r_dataframe
    except we don't convert the index into strings


    We are just grabbing the column data here
    """

    import rpy2.rlike.container as rlc

    columns = rlc.OrdDict()

    #FIXME: This doesn't handle MultiIndex

    for column in df:
        value = df[column]
        value_type = value.dtype.type
        value = [item if pd.notnull(item) else NA_TYPES[value_type]
                 for item in value]

        value = VECTOR_TYPES[value_type](value)

        if not strings_as_factors:
            I = robjects.baseenv.get("I")
            value = I(value)

        columns[column] = value

    r_dataframe = robjects.DataFrame(columns)
    return r_dataframe

def _localize_tz(df):
    """
        We don't have the option of naive timestamps in R. 
        If we pass in timezone-less data, it will be converted to our
        system's TZ. This will result in silent errors since R doesn't raise
        a NonExistentTimeError.
    """
    ind = df.index
    if ind.tz is None:
        ind = ind.tz_localize('UTC')
    df.index = ind
    return df

def convert_df_to_xts(df, strings_as_factors=False):
    df = _localize_tz(df)
    r_dataframe = XTS(df)
    return r_dataframe

def convert_datetime_index_string(ind):
    """
        Convert to POSIXct via strings
    """
    rownames = robjects.StrVector(ind)
    tz = ind.tz.zone
    # convert m8[ns] = ms8[s]
    asposix = robjects.r.get('as.POSIXct')
    return asposix(rownames, origin="1970-01-01", tz=tz)

def convert_datetime_index_num(ind):
    """
        Convert to POSIXct using m8[s] format
        see robject.vectors.POSIXct where I grabbed logic
    """
    # convert m8[ns] to m8[s]
    vals = robjects.vectors.FloatSexpVector(ind.asi8 / 1E9)
    as_posixct = baseenv_ri['as.POSIXct']
    origin = StrSexpVector([time.strftime("%Y-%m-%d", 
                                          time.gmtime(0)),])
    # We will be sending ints as UTC
    tz = ind.tz and ind.tz.zone or 'UTC'
    tz = StrSexpVector([tz])
    utc_tz = StrSexpVector(['UTC'])

    posixct = as_posixct(vals, origin=origin, tz=utc_tz)
    posixct.do_slot_assign('tzone', tz)
    return posixct

def convert_datetime_index(o):
    return POSIXct(o)

class XTS(RObject):
    """ R 'as.xts'.
    """
    
    def __init__(self, df):
        """ Create a xts.
        """
        self.rdf = None
        if isinstance(df, pd.DataFrame):
            rdf = convert_dataframe_columns(df)
            ind = convert_datetime_index_num(df.index)
            kv = [('x', rdf), ('order.by', ind)]
            kv = tuple(kv)
            xts = baseenv_ri.get("as.xts").rcall(kv, globalenv_ri)
            super(XTS, self).__init__(xts)
        else:
            raise ValueError("Currently only supporting DataFrames")
    
    def __repr__(self):
        return self.rdf.__repr__()

class POSIXct(robjects.vectors.FloatVector):
    """ R 'as.POSIXct'.
    """
    
    def __init__(self, ind):
        """ Create a POSIXct.
        """
        if isinstance(ind, pd.DatetimeIndex):
            posixct = convert_datetime_index_num(ind)
            super(POSIXct, self).__init__(posixct)
        else:
            raise ValueError("Currently only supporting DataFrames")

robjects.conversion.py2ri = pd_py2ri
