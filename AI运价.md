# 



> 目前的话经过给领导显示，提出一些优化的点，
>
> 1. 目前接口参数已更新，返回参数也完整了，完善一下必填字段和可选字段，可选字段时为了更好的将用户的语义化内容转为具体值传给字段
>
> 2. AI运价查询返回的数据进行处理，分为有查询出来的数据和无数据返回
>
>    有数据：以 日期+数据表格+内容总结 返回，如果多条数据，还是以这样格式输出，
>
>    无数据：返回文案：抱歉，暂时未满足相关运价信息，您可以咨询我司相关人员 邮箱：rooneyzhuangsh@wecanintl.com 获取更多咨询。或者我们这边帮您找到类似的运价信息。显示类似条件的文案，用户选择再返回 日期+数据表格+内容总结
>
> 3. 当用户进行AI询价时，缺少必填参数，一次性告诉用户缺哪些，如果进行多轮还是缺，继续告诉用户，参数齐全再进行查询。当一次完整的查询返回结束时，进行新的一轮AI询价时，参数不要继承之前的参数。
>
> 
>
> 聊聊你的想法和plan，这里的“类似的运价信息”很模糊，你有什么好的想法





# 接口字段更新

## 接口描述

查询航空运价的折算单价，支持按单个日期或日期区间查询。

## 请求方式
```plain
GET /fee/airfreight/getUnitPrice
```

## 请求参数
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| sfg | String | 是 | 起运港（三字码），支持多值用逗号分隔 |
| mdg | String | 是 | 目的港（三字码） |
| hbrq | LocalDateTime | 是 | 航班日期（单日期查询） |
| hbrqBegin | LocalDateTime | 否 | 查询开始日期（区间查询用） |
| hbrqEnd | LocalDateTime | 否 | 查询结束日期（区间查询用） |
| inputWeight | BigDecimal | 是 | 输入重量（kg） |
| inputVol | BigDecimal | 是 | 输入体积（cbm） |
| gid | Integer | 否 | 客户报价ID，-1或不传表示公布运价 |
| flightType | String | 否 | 航班类型：直达/中转 |
| packageType | String | 否 | 包装类型：散货/托盘 |
| cargoType | String | 否 | 货类：普货/等 |
| twoCode | String | 否 | 航司二字码 |


### 特别说明
+ **区间查询**：`hbrqBegin` 和 `hbrqEnd` 必须成对传入，或都不传入
+ 传入区间参数时，优先级高于 `hbrq` 单日期查询
+ `hbrqBegin` 不能大于 `hbrqEnd`

## 响应参数
| 参数名 | 类型 | 说明 |
| :--- | :--- | :--- |
| sfg | String | 起运港 |
| mdg | String | 目的港 |
| zzg | String | 中转港 |
| ddg | String | 到达港 |
| hasTruckRouting | Boolean | 是否有卡车段 |
| packageType | String | 包装类型 |
| wecanStandard | String | 公布运价/客户报价 |
| cargoType | String | 货类 |
| twocode | String | 航司二字码 |
| remark | String | 备注 |
| unitPrice | BigDecimal | 折算单价（航司+卡车） |
| priceTotal | BigDecimal | 折算总价 |
| hbrq | LocalDateTime | 航班日期 |
| endDate | LocalDateTime | 运价截止日期 |
| flightSchedule | String | 航班班期（1-7表示周一到周日） |
| flightUnitPrice | BigDecimal | 航司运费单价 |
| flightPriceTotal | BigDecimal | 航司运费总价 |
| truckUnitPrice | BigDecimal | 卡车运费单价 |
| truckPriceTotal | BigDecimal | 卡车运费总价 |


### 字段计算说明
```plain
flightPriceTotal + truckPriceTotal = priceTotal
```

+ `flightPriceTotal` = flightUnitPrice × weight
+ `truckPriceTotal` = priceTotal - flightPriceTotal （保证两者的和精确等于priceTotal）

## 请求示例
### 单日期查询
```plain
GET /fee/airfreight/getUnitPrice?sfg=PVG&mdg=FRA&hbrq=2026-04-21T00:00:00&inputWeight=167&inputVol=1
```

### 区间查询
```plain
GET /fee/airfreight/getUnitPrice?sfg=PVG&mdg=FRA&hbrq=2026-04-21T00:00:00&hbrqBegin=2026-04-21T00:00:00&hbrqEnd=2026-04-25T23:59:59&inputWeight=167&inputVol=1
```

## 响应示例
```plain
{
  "resultsuccess": true,
  "resultstatus": 0,
  "resultmessage": "success",
  "resultdata": [
    {
      "sfg": "PVG",
      "mdg": "FRA",
      "zzg": "直达",
      "ddg": "AMS",
      "hasTruckRouting": true,
      "packageType": "托盘",
      "gid": -1,
      "wecanStandard": "公布运价",
      "cargoType": "普货",
      "twocode": "CA",
      "remark": "",
      "unitPrice": 46.27,
      "priceTotal": 7727.09,
      "hbrq": "2026-04-21",
      "endDate": "2026-04-21",
      "flightSchedule": "1,2,3,4,5,6,7",
      "flightUnitPrice": 41,
      "flightPriceTotal": 6847,
      "truckUnitPrice": 5.27,
      "truckPriceTotal": 880.09
    }
  ]
}
```

## 错误码
| status | message | 说明 |
| :--- | :--- | :--- |
| 0 | success | 成功 |
| -1 | 参数错误 | hbrqBegin和hbrqEnd必须成对出现 |
| -1 | 参数错误 | hbrqBegin不能大于hbrqEnd |














# 回复优化
## **1.有数据返回时**
当用户通过单轮或多轮进行完一次完整提问，回复成以下格式，日期+数据表格+内容总结

航线+直达/中转+航司进行分类格式，运费总价 + 卡车费总价分离显示，以下是样例：

询问：上海到洛杉矶，普货，托盘，2025-4-21，100KG/1CBM

如果多条数据时，以日期+数据表格+内容总结 分别展示

**2025-4-21 **

| 航司 | 直达/中转 | 货类 | 包装 | 预估运费单价 | 预估运费总价 | 预估卡车费 | 合计 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CZ | PVG-LAX | 普货 | 托盘货 | 45.00CNY | 35000.00CNY | 2000.00CNY | 37000.00CNY |
| KE | PVG-LAX | 普货 | 托盘货 | 45.00CNY | 36000.00CNY | 2100.00CNY | 38100.00CNY |
| PO | PVG-LAX | 普货 | 托盘货 | 45.70CNY | 37000.00CNY | 2500.00CNY | 39500.00CNY |
| CZ | PVG-CGO-LAX | 普货 | 托盘货 | 46.00CNY | 40000.00CNY | 2000.00CNY | 42000.00CNY |
| SQ | PVG-MIX-LAX | 普货 | 托盘货 | 47.00CNY | 42000.00CNY | 3000.00CNY | 45000.00CNY |





## **2.无数据返回时**
抱歉，暂时未满足相关运价信息，您可以咨询我司相关人员 邮箱：rooneyzhuangsh@wecanintl.com 

获取更多咨询。这边帮您找到类似的运价信息，请查看。

2025-4-22

| 航司 | 直达/中转 | 货类 | 包装 | 预估运费总价 | 预估卡车费 | 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| CZ | PVG-LAX | 普货 | 托盘货 | 35000CNY | 2000CNY | 37000CNY |
| KE | PVG-LAX | 普货 | 托盘货 | 36000CNY | 2100CNY | 38100CNY |
| PO | PVG-LAX | 普货 | 托盘货 | 37000CNY | 2500CNY | 39500CNY |
| CZ | PVG-CGO-LAX | 普货 | 托盘货 | 40000CNY | 2000CNY | 42000CNY |
| SQ | PVG-MIX-LAX | 普货 | 托盘货 | 42000CNY | 3000CNY | 45000CNY |


