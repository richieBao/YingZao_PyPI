# -*- coding: utf-8 -*-
"""
Created on Fri Sep  6 08:24:25 2024

@author: richie bao
"""
def sine_PSA(sequence, period, shift, amplitude):
    '''
    计算正弦曲线x,y值

    Parameters
    ----------
    sequence : list
        序列值.
    period : numerical
        正弦函数周期.
    shift : numerical
        正弦函数偏移.
    amplitude : numerical
        正弦函数振幅.

    Yields
    ------
    iterable
        正弦值.
    '''

    for v in sequence:
        if amplitude:
            yield amplitude*math.sin((1/period)*v+math.pi/2+shift)
        else:
            yield math.sin((1/period)*v+math.pi/2+shift)
