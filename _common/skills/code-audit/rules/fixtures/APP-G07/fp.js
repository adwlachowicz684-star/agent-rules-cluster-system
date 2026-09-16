// FP1：非相对导入（包名）——不参与文件系统解析，本规则只判 ./ 与 ../
import React from 'react'
import { format } from 'date-fns'

export function render() {
  return React.createElement('div', null, format(new Date()))
}
