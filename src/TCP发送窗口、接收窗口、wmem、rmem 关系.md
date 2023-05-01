---
layout: post
title: TCP 发送窗口、接收窗口、wmem、rmem 关系
slug: TCP_Buffer
date: 2023-05-01 14:00
status: publish
author: Sai
categories: 
  - Maverick
tags:
  - TCP
excerpt: TCP 发送窗口、接收窗口、wmem、rmem 关系
---

# 基础环境

**服务器信息**

Client：192.168.56.100

Server：192.168.56.101

OS：CentOS Linux release 7.9.2009 (Core)	3.10.0-1160.el7.x86_64

**大致思路**

wmem 对应 `Send Buffer`，从 TCP 的概念可以理解为 发送窗口，字母 `w` 可以理解成 `write`

rmem 对应 `Receive Buffer`，从 TCP 的概念可以理解为 接收窗口

实验过程是模拟一个下载过程，也就是大致过程是 `server` 发送文件，所以调整 `wmwm`，`client` 接收文件，所以调整 rmen

**目的如下：**

```wiki
写死 Linux参数让传输速度慢下来
改接收端：sysctl -w "net.ipv4.tcp_rmem=4096	4096	4096"
或者
改发送端：sysctl -w "net.ipv4.tcp_wmem=4096	4096	4096" 

继续调整rtt、丢包率，curl限制速度等，抓包分析看到的所有现象
```

**系统默认参数如下**

```bash
$ sudo sysctl -a | egrep "rmem|wmem|tcp_mem|adv_win|moderate"
net.core.rmem_default = 212992
net.core.rmem_max = 212992
net.core.wmem_default = 212992
net.core.wmem_max = 212992
net.ipv4.tcp_adv_win_scale = 1
net.ipv4.tcp_mem = 42459	56612	84918
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_rmem = 4096	87380	6291456	//最小值  默认值  最大值
net.ipv4.tcp_wmem = 4096	16384	4194304	//最小值  默认值  最大值
net.ipv4.udp_rmem_min = 4096
net.ipv4.udp_wmem_min = 4096
vm.lowmem_reserve_ratio = 256	256	32
```

**开始命令**

```bash
# Client && Server
clientIP="192.168.56.100"
serverIP="192.168.56.101"

# Server
# 启动命令的地方存在一个 2个多G 的文件
python -m SimpleHTTPServer 8089

## Client
curl http://192.168.56.101:8089/iso.tar --output ./result

# 测试宽带
iperf3 -s
iperf3 -c ${serverIP} -t 60 -i 1
# 无额外设置情况下宽带结果
大概是 2.69 Gbits/sec = 2860 Mbps
```

**实验结果信息汇总**

```bash
--正常 127 MB/s

--延时 100ms，5.48 MB/s
client 角度看的话，server发的包大小不稳定，60000-10000都有
server 是以比较稳定的处理包，然后有100ms的延时

--延时 100ms 且client 的 rmem 改成 4096，17 KB/s
client 角度来看，包比较乱
server 角度来说，连续小包（几千的样子）汇总发送,包的大小会有 重复递增的样子

--延时 100ms 且server 的 wmem 改成 4096，80 KB/s
client 角度来看，一个ACK，然后一个稳定的接收 8258 length 的包
server 是以比较稳定的处理包，然后有100ms的延时

--延时 10ms 且client 的 rmem 改成 4096，17 KB/s
client 角度来看，包比较乱
server 角度来说，连续小包（几千的样子）汇总发送,包的大小会有 重复递增的样子

--延时 100ms 且server 的 rmem 改成 4096，4.87 MB/s[只是记录用]
client 角度来看，包比较乱
server 角度来说，连续小包（几千的样子）汇总发送,包的大小会有 重复递增的样子
```



# 实验记录

## 实验一：正常状态

```bash
# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_01.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_01.pcap

# 下载结果 大概平均下载速度是 127 MB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result_01
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100 2539M  100 2539M    0     0   127M      0  0:00:19  0:00:19 --:--:--  130M
```

可以看到截图里，时间都是以 0.000X 秒递增的

client_01 截图

![](https://raw.githubusercontent.com/iYangcw/Photo/master/client_01.png)

server_01 截图

![](https://raw.githubusercontent.com/iYangcw/Photo/master/server_01.png)

### TCP  Windows  Scale

Window Scale 选项只能与 TCP SYN、SYN/ACK 一起使用。TCP 早期的时候带宽很小，所以最大接收窗口被定义成 65535 字节（ TCP Header 的 Windows 最大为 16 bit ）

由于不够用，所以通过 TCP options 定义了 Windows  Scale，其声明了一个 Shift count，作为2的指数，再乘以 TCP 头中定义的接收窗口，就得到真正的 TCP 接收窗口了。

下图为 SYN/ACK 中可以看到 Windows  Scale 为 7

![image-20230420161433041](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230420161433041.png)

下图为真实的 Windows size：29312 = 229 * 128

![image-20230420161615849](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230420161615849.png)

### Window size

TCP 层的 Windows size （或者如上述截图的 Windows 、Calculated windows size），是在向对方声明自己的**接收窗口**，而不是发送窗口

发送窗口决定了一口气能发多少字节，而 MSS 决定了这些字节要分多少个包发完。至于为什么 MSS=1460 的情况下，但是抓包的结果仍然有大于他的，这就是另外一个故事了，关键字：TCP Segment Offload



## 实验二：server 增加 100ms 延时

```bash
# Server
tc qdisc show dev enp0s8
tc qdisc del dev enp0s8 root
tc qdisc add dev enp0s8 root netem delay 100ms
# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_delay_100ms.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_delay_100ms.pcap

# 结果，大概平均下载速度是 5.48 MB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
100 2539M  100 2539M    0     0  5619k      0  0:07:42  0:07:42 --:--:-- 4563k
```

server 抓包详情

![image-20230423133802553](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230423133802553.png)

Wireshark 菜单路径：Statistics >> TCP Stream Graphs >> Time Sequence （Stevens）

![](https://raw.githubusercontent.com/iYangcw/Photo/master/server_dely_100ms.png)



## 实验三：server 增加 100ms 延时，client 修改 rmem

```bash
# 两边原始值
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"
sysctl -w net.ipv4.tcp_rmem="4096 87380 6291456"
# server
tc qdisc show dev enp0s8
tc qdisc del dev enp0s8 root
tc qdisc add dev enp0s8 root netem delay 100ms
# client
sysctl -w net.ipv4.tcp_rmem="4096 4096 4096"

# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_delayServer_100ms_rmem_Client_4096.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_delayServer_100ms_rmem_Client_4096.pcap

# 结果, 大概平均下载速度是 17 KB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result_01
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0 2539M    0 1399k    0     0  14436      0 51:14:22  0:01:39 51:12:43 14458
```



## 实验四：server 增加 100ms 延时，server 修改wmem

```bash
# 两边原始值
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"
sysctl -w net.ipv4.tcp_rmem="4096 87380 6291456"
# Server
tc qdisc show dev enp0s8
tc qdisc del dev enp0s8 root
tc qdisc add dev enp0s8 root netem delay 100ms
sysctl -w net.ipv4.tcp_wmem="4096 4096 4096"
# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_delayServer_100ms_wmem_Server_4096.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_delayServer_100ms_wmem_Server_4096.pcap

# 结果, 大概平均下载速度是 80 KB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result_03
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0 2539M    0 13.3M    0     0  81082      0  9:07:22  0:02:52  9:04:30 81157
```

![image-20230426200129823](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230426200129823.png)

Window Scaling 截图，绿线后面稳定的时候，值是 182272，和抓包截图里 Client 的 win=182272 也对应的上，win 是 client 向对方声明自己的接收窗口。从下载网速来看也就是虽然 client 声明了自己的接收窗口很大，但是 server 端的 wmem 比较小，所以网速也不快。

![image-20230426193723153](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230426193723153.png)

一个笔直的蓝色线 对应的从 No 180-182，对应的大小为：2896、5792、8192，抓包见下面截图，和抓包详情截图的 Len 字段也对得上。

wireshark 的 Length 列 减去 66 ，就等于包详情里的 Len，至于为什么是 66 不太清楚，但是可以从 ACK 响应是 66 辅助确认。

![image-20230426195023142](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230426195023142.png)



## 实验五：server 增加 10ms 延时，client 修改 rmem

```bash
# 两边原始值
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"
sysctl -w net.ipv4.tcp_rmem="4096 87380 6291456"
# Server
tc qdisc show dev enp0s8
tc qdisc del dev enp0s8 root
tc qdisc add dev enp0s8 root netem delay 10ms
# client
sysctl -w net.ipv4.tcp_rmem="4096 4096 4096"

# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_delayServer_10ms_rmem_Client_4096.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_delayServer_10ms_rmem_Client_4096.pcap

# 结果, 大概平均下载速度是 123 KB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result_01
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
  0 2539M    0 20.6M    0     0   123k      0  5:50:08  0:02:50  5:47:18  123k
```



## 实验六：server 增加 100ms 延时，server 修改 rmem

```bash
# Server
tc qdisc show dev enp0s8
tc qdisc del dev enp0s8 root
tc qdisc add dev enp0s8 root netem delay 100ms
sysctl -w net.ipv4.tcp_wmem="4096 16384 4194304"
sysctl -w net.ipv4.tcp_rmem="4096 4096 4096"
# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_delayServer_100ms_rmem_4096.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_delayServer_100ms_rmem_4096.pcap

# 结果, 大概平均下载速度是 4.87 KB/s
$ curl http://192.168.56.101:8089/iso.tar --output ./result_04
  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                 Dload  Upload   Total   Spent    Left  Speed
 63 2539M   63 1599M    0     0  4991k      0  0:08:40  0:05:28  0:03:12 4030k
```



## 实验七：curl 增加速度控制

```bash
# client & server 保持默认值不动，限速设置小一点，感觉抓包分析更好一点，分别尝试了1k、100k、1M
curl --limit-rate 1k http://192.168.56.101:8089/iso.tar --output ./result_04

# Client
tcpdump -i enp0s8 -n host  ${serverIP} -w client_curl_1k.pcap
# Server
tcpdump -i enp0s8 -n host  ${clientIP} -w server_curl_1k.pcap

```

TCP Window Full 意味着窗口填满，可以看下这篇文章，说的很详细：[Analyse Slow Networks with TCP Zero Window](https://www.golinuxcloud.com/wireshark-tcp-zero-window/)

![image-20230427171447952](https://raw.githubusercontent.com/iYangcw/Photo/master/image-20230427171447952.png)



# 结论

## 结论一：改小 client rmem 和 server wmem 来对比对速度的影响

**实验三 和 实验四**：平均下载速度为：17 KB/s 和 80 KB/s 的对比

相比而言，server 改小了 wmen 速度还凑合，因为server 每次收到ack，立即释放 wmem 来发新的网络包 (内存级别的时延)；

如果 client 的 rmem 比较小，当 rmem 满了到应用读走 rmem，rmem 有空闲后需要 rtt 时间反馈到 server 端，server 端才会继续发包。（网络级时延比内存级时延高几个数量级）

一句话总结：就是 rmem 从有空到包进来会有很大的间隔 (rtt) , wmem 有空到写包进来没有时延。

plantegg 任总的这张图反复看，能有点理解了

![](https://raw.githubusercontent.com/iYangcw/Photo/master/server%20_wmem_client_%20rmem.png)

时间比较

![](https://raw.githubusercontent.com/iYangcw/Photo/master/time.png)

分析 实验三和实验四中 server 端抓包的结果：

实验三 rmen 的截图，从 No 15 开始看，差不多是 server > client，【TCP Window Full 过会看】然后 No 17 中，client > server ACK 回复，然后过了 0.1 秒，No 18 又开始发送给 client 了。

而且 TCP Window Full 很频繁，窗口被填满了，所以下载的速度很慢。截图里能看到 source=client ip 的 win=1460。

简单按照步骤描述下过程

1、No 11: client 表示我的接收窗口为 1460

2、No 12: server 表示我的接收窗口为 29056，以及发送了 730 长度的包

3、No 13: server 继续发送了 730 长度的包，由于 730 + 730 等于 client 的接收窗口 1460，所以提示 TCP WIndow Full

4、No 14: client 继续说我的接收窗口为 1460



实验四 wmen 的截图，server 几个包发给 client，然后 client ack 回复，反复该过程，包的发送比较平稳

![](https://raw.githubusercontent.com/iYangcw/Photo/master/rmem_client_4096.png)

![](https://raw.githubusercontent.com/iYangcw/Photo/master/wmem_server_4096.png)

## 结论二：rmem 改小，查看 调整 rrt 后来对比速度

**实验三 和 实验五** 都是修改 client rmen = 4096，只是一个是 server 端设置了 100ms 和 10ms 延时，但是结果是 17 KB/s 和 123 KB/s 的差距。

rrt 增大了，下载速度会下降。

plantegg 任总的这张图反复看【**结论二的只需要看图片左边即可**】，能有点理解了

延时增加了，那说明链路上的包也多了，client 接收包的速度慢了，那自然下载速度变慢。

BDP 由于和带宽有关，但是两台虚拟机的带宽，目前我计算还有点问题，不清楚是原始状态进行 iperf3 计算，还是调整了系统参数再去计算，目前 BDP 的理解还不够深，以下是 BDP 的计算方法。

**BDP 举例计算信息如下**

BDP来设置最大接收窗口（可计算出最大读缓存）。BDP叫做带宽时延积，也就是带宽与网络时延的乘积，例如若我们的带宽为2Gbps，时延为10ms，那么带宽时延积BDP则为2G/8 * 0.01=2.5MB，所以这样的网络中可以设最大接收窗口为2.5MB

![rmem_rtt](https://raw.githubusercontent.com/iYangcw/Photo/master/rmem_rtt.png)

## 结论三：网速和 wmem rmem rtt 带宽 的关系

减少 rtt

增大带宽

增加 server 的 send buffer （对应 wmem）

增加 client 的 recv buffer （对应 rmem）



# ss 计算 tcp buffer size

[man ss 链接](https://man7.org/linux/man-pages/man8/ss.8.html)

```bash
# 注意下，tb 表示 snd_buf，字母 t 可以理解为 Transmit
       -m, --memory
              Show socket memory usage. The output format is:

              skmem:(r<rmem_alloc>,rb<rcv_buf>,t<wmem_alloc>,tb<snd_buf>,
                            f<fwd_alloc>,w<wmem_queued>,o<opt_mem>,
                            bl<back_log>,d<sock_drop>)
```



# 参考链接

[Analyse Slow Networks with TCP Zero Window](https://www.golinuxcloud.com/wireshark-tcp-zero-window/)

[TCP性能和发送接收窗口、Buffer的关系](https://plantegg.github.io/2019/09/28/%E5%B0%B1%E6%98%AF%E8%A6%81%E4%BD%A0%E6%87%82TCP--%E6%80%A7%E8%83%BD%E5%92%8C%E5%8F%91%E9%80%81%E6%8E%A5%E6%94%B6Buffer%E7%9A%84%E5%85%B3%E7%B3%BB/)

[长肥管道(LFT)中TCP的艰难处境与打法](https://blog.csdn.net/dog250/article/details/113020804)

[Why Your Application only Uses 10Mbps Even the Link is 1Gbps?](https://www.cisco.com/c/en/us/support/docs/ip/transmission-control-protocol-tcp/200943-Why-Your-Application-only-Uses-10Mbps-Ev.html)





