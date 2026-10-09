# SC6103 分布式航班信息系统原型

Python 3.10+，只用标准库，无需安装第三方包。客户端和服务器均使用 UDP；没有数据库或图形界面。

## 快速启动

在本目录打开两个终端（PowerShell 可先运行 `cd D:\2026-2027NTUMSC\T1\SC6103\flight_system`）。

终端 1 启动服务器：

```powershell
python server.py --mode amo
```

终端 2 启动交互客户端：

```powershell
python client.py --mode amo
```

菜单包含路线查询、航班详情、订座、监控、设置票价、增加票价以及退出。服务器与客户端的 `--mode` 必须一致：`amo` 表示至多一次，`alo` 表示至少一次重试策略。

初始数据：101 和 102 是 Singapore → Tokyo；103 是 Singapore → Shanghai。101 初始 100 个座位、票价 500。每次重启服务器会重置所有数据。

也可以直接执行一个操作：

```powershell
python client.py search Singapore Tokyo
python client.py details 101
python client.py reserve 101 2
python client.py set-fare 101 600
python client.py add-fare 101 10
```

票价为浮点数；起飞时间以 UTC 显示。

## 监控演示

服务器保持运行，再打开两个客户端终端：

```powershell
# 客户端 A：监控 30 秒，期间阻塞菜单输入
python client.py monitor 101 30
```

看到注册成功后，在客户端 B 执行：

```powershell
python client.py reserve 101 2
```

客户端 A 会显示包含 flight_id、seats、sequence 的通知。可再启动其他监控客户端，验证同一次订座通知多个订阅者；订阅到期后服务器清理记录。

## 三台电脑演示

1. 三台电脑连接可互通的局域网。服务器电脑运行 `python server.py --host 0.0.0.0 --port 9000 --mode amo`。
2. 在服务器电脑用 `ipconfig` 查看局域网 IPv4 地址。
3. 两台客户端电脑把 `--host` 指向该地址，例如 `python client.py --host 192.168.1.20 --mode amo`。这里的地址只是示例，必须替换。
4. 一台监控，另一台订座。若无法连接，检查局域网客户端隔离以及服务器防火墙对 Python/UDP 9000 的入站许可。

## 丢包及调用语义实验

最直观的手工实验：启动全新服务器，丢弃第一条响应，然后直接订座，避免先查询消耗该丢包开关。

```powershell
python server.py --mode alo --drop-first-reply
python client.py --mode alo reserve 101 2
```

预期剩余 96：第一次已经扣座，但响应丢失；客户端重试后再次扣座。停止服务器，改用 `amo` 重启，再以 `--mode amo` 订座，剩余 98。

概率丢包：服务器支持 `--request-loss 0.2 --reply-loss 0.2 --seed 1`。丢请求发生在执行业务之前，丢响应发生在执行并缓存之后。回调不经过这两个模拟丢包开关。

自动生成 12 组真实 UDP 实验结果：

```powershell
python experiments.py
```

输出写入 `EXPERIMENT_RESULTS.md`。每组重新启动独立服务器，比较两种模式下订座、设置票价、增加票价的正常情况和首次响应丢失情况。

自动测试：

```powershell
python -m unittest -v test_system
```

## 四人接手分工

| 成员 | 代码和说明 | 下一步重点 |
|---|---|---|
| A | protocol.py、PROTOCOL.md | 理解字段、字节序、长度前缀和消息边界，审查协议 |
| B | server.py 的航班业务 | 完善业务校验、准备演示航班数据、检查额外操作 |
| C | client.py、server.py 的订阅与 notify | 操作体验、跨电脑运行、多个监控客户端 |
| D | client.py 的重试、server.py 的 history、测试与实验 | 理解去重、复现实验、整理报告数据 |

`REPORT_DRAFT.md` 是技术报告草稿；成员姓名、真实贡献比例和跨电脑验证记录需要你们补充。

## 设计边界

- AMO 去重键是随机 128 位客户端标识加单调递增请求编号；重试保持相同 ID。不同客户端可独立从 1 编号。相同 ID 携带不同内容会被拒绝。
- 历史缓存保留整个服务器进程生命周期，不做淘汰；因此长时间运行会增加内存使用。重启后无去重或数据恢复保证。
- 有限重试耗尽时，客户端报告“结果未知”。这不代表业务一定失败；服务器可能已执行但所有响应都丢失。此时应先查询状态。
- UDP 回调为尽力通知，无确认或补发；客户端使用通知序号忽略重复或倒序通知。任务要求发送每次更新，本原型未扩展为可靠通知协议。
- 服务器端监控时长从处理注册开始计算。客户端在收到确认后等待指定时长，因此在注册确认延迟时可能多等待一小段时间；服务器仍按注册时间停止推送。AMO 重试不会延长服务器端订阅。
- 单线程服务器处理请求；演示和测试中的多个线程仅用于同时启动独立客户端、服务器，不是业务服务器的多线程实现。
- 无认证、支付、持久化或生产部署设计；这是课程实验原型。

## 提交前

本机回环通信测试不能代替三台电脑演示。请按原课程文件核对提交要求，填写组员信息并完成跨电脑演练。课程文件的提交日期是 2026-10-14，演示日期是 2026-10-17。
