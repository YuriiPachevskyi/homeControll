#!/bin/bash

setI2CRegisterEnabled() {
    i2cRegister=$1
    i2cPin=$2
    currentValue=`i2cget -y 1 $i2cRegister`
    i2cset -y 1 $i2cRegister $(($currentValue & (0xFF ^ $i2cPin)))
}

setI2CRegisterDisabled() {
    i2cRegister=$1
    i2cPin=$2
    currentValue=`i2cget -y 1 $i2cRegister`

    i2cset -y 1 $i2cRegister $(($currentValue | $i2cPin))
}

