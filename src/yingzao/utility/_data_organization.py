# -*- coding: utf-8 -*-
"""
Created on Sat Aug 17 19:07:15 2024

@author: richie bao
"""


# 嵌套列表展平
flatten_lst=lambda lst: [m for n_lst in lst for m in flatten_lst(n_lst)] if type(lst) is list else [lst]


def nestedListGrouping4(nested_lst):
    '''
    将一个嵌套列表（矩阵）转化为邻接4点（值）组织的模式

    Parameters
    ----------
    nested_lst : List
        嵌套列表（矩阵）.

    Returns
    -------
    grouped : List
        矩阵中邻接4点为一组的列表.

    '''
    grouped=[]
    for m in range(len(nested_lst)-1):
        a=nested_lst[m]
        b=nested_lst[m+1]
        for i in range(len(a)-1):
            lst=[]
            lst.append(b[i])
            lst.append(a[i])            
            lst.append(a[i+1])
            lst.append(b[i+1])
            grouped.append(lst)
    return grouped

def recursive_add(current, increment, limit,vals_lst):
    '''
    指定开始值（current）、步幅值(increment)和最大值(limit)，建立序列，存储于 vals_lst 列表中

    Parameters
    ----------
    current : float | int
        开始值.
    increment : float | int
        步幅值.
    limit : float | int
        最大值.
    vals_lst : List
        列表.

    Returns
    -------
    List[float | int]
        序列值.

    '''
    # Base case: if current value exceeds the limit, return it    
    if current > limit:
        vals_lst.append(current)
        return current
    vals_lst.append(current)
    # Recursive case: add the increment to the current value and call the function again
    return recursive_add(current + increment, increment, limit,vals_lst)

def range_SES(start, end, step):
    '''
    给定开始、结束值和步幅值，返回序列。可以计算小数

    Parameters
    ----------
    start : numerical
        开始值.
    end : numerical
        结束值.
    step : numerical
        步幅值.

    Yields
    ------
    s_v : iterable
       序列.
    '''

    s_v = start
    while s_v < end:
        yield s_v
        s_v += step

if __name__=="__main__":
    vals_lst=[]
    recursive_add(3.1,0.2,10,vals_lst)
    print(vals_lst)



