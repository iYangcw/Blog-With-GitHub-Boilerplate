---
layout: post
title: 通过 netns 以及 veth bridge 类型创建 IP
slug: 通过 netns 以及 veth bridge 类型创建 IP
date: 2023-08-17 09:00
status: publish
author: Sai
categories: 
  - Maverick
tags:
  - TCP
excerpt: 通过 netns 以及 veth bridge 类型创建 IP

---

# 1、通过 netns 以及 veth bridge 类型创建 IP

**链接**

[ip netns man url](https://man7.org/linux/man-pages/man8/ip-netns.8.html)

[ip link man url](https://man7.org/linux/man-pages/man8/ip-link.8.html)

[Introduction to Linux interfaces for virtual networking](https://developers.redhat.com/blog/2018/10/22/introduction-to-linux-interfaces-for-virtual-networking#bridge)

[How Do Kubernetes and Docker Create IP Addresses?](https://dustinspecker.com/posts/how-do-kubernetes-and-docker-create-ip-addresses/)

**相关信息**

服务器信息：CentOS Linux release 7.9.2009 (Core)	3.10.0-1160.el7.x86_64

netns 信息

| netns name     | host device and IP    | netns device and IP      |
| -------------- | --------------------- | ------------------------ |
| ns_dustin      | veth_dustin/10.0.0.10 | veth_ns_dustin/10.0.0.11 |
| veth_ns_dustin | veth_leah/10.0.0.20   | veth_ns_leah/10.0.0.21   |

bridge 信息

`bridge_home 10.0.0.1`

下述操作学到一点，就是网络访问异常的时候，又不确认是防火墙那个策略导致，可以通过下述操作一点点倒推。

```bash
#通过 diff 的差异来进行比较，一点点倒推；下述操作遇到的异常大部分是通过这个倒推的，不知道有什么更精确的方法来定位是那个 firewalld 导致的
iptables --line-number -t filter -nvxL > 1.filter
发起 ping curl 等操作
iptables --line-number -t filter -nvxL > 2.filter
diff 1.filter 2.filter
```

## netns and loopback device

创建 netns 以及启动 netns 下的 loopback device

```bash
host server 
python3 -m http.server 8080
# Create netns
sudo ip netns add netns_dustin
# show all of the named network namespaces，其实信息位于 /var/run/netns
sudo ip netns list
# netns server
sudo ip netns exec netns_dustin python3 -m http.server 8080

# 刚开始 loopback 设备状态为 DOWN
sudo ip netns exec netns_dustin ip address list
1: lo: <LOOPBACK> mtu 65536 qdisc noop state DOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00

# 启动，lo 状态变为 UNKNOWN ，不是 UP ，但是不影响
sudo ip netns exec netns_dustin ip link set dev lo up
# 可以访问 netns 下的端口了
sudo ip netns exec netns_dustin curl localhost:8080
```

## Create veth ：Virtual ethernet interface

```bash
sudo ip link add dev veth_dustin type veth peer name veth_ns_dustin

# 可以看到两个设备的状态均为 DOWN
ip link list
6: veth_ns_dustin@veth_dustin: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
    link/ether 82:0a:e9:66:7f:40 brd ff:ff:ff:ff:ff:ff
7: veth_dustin@veth_ns_dustin: <BROADCAST,MULTICAST,M-DOWN> mtu 1500 qdisc noop state DOWN mode DEFAULT group default qlen 1000
    link/ether 0e:c1:c3:7d:fa:b6 brd ff:ff:ff:ff:ff:ff
    
sudo ip link set dev veth_dustin up

# move veth_ns_dustin device to the netns_dustin network namespace
sudo ip link set veth_ns_dustin netns netns_dustin

# 再执行 ip link list 能看到 veth_ns_dustin 设备不在了

sudo ip netns exec netns_dustin ip link list
sudo ip netns exec netns_dustin ip link set dev veth_ns_dustin up
```

## Create Virtual IP Addresses For veth

```bash
sudo ip address add 10.0.0.10/24 dev veth_dustin
sudo ip netns exec netns_dustin ip address add 10.0.0.11/24 dev veth_ns_dustin
```

此时，互相 ping 以及本机调用 netns 下的服务，网络正常

```bash
相互 ping 正常
ping 10.0.0.10 -c 1
ping 10.0.0.11 -c 1
sudo ip netns exec netns_dustin ping 10.0.0.10 -c 1
sudo ip netns exec netns_dustin ping 10.0.0.11 -c 1
# 本机访问 netns 端口正常
curl 10.0.0.11:8080
```

netns 调用本机 veth device IP 服务

```bash
如果主机没有开启防火墙，正常是能通的；本次测试的主机 firewalld 是开启的，以下命令异常
# 提示 curl: (7) Failed connect to 10.0.0.10: 8080; No route to host ，按照如下操作开启 8080/tcp 放开
sudo ip netns exec netns_dustin curl 10.0.0.10:8080

# 经排查，可能是由于本机 firewalld 启动导致，把 8080 端口放开后，再调用上述命令正常
firewall-cmd --zone=public --add-port=8080/tcp --permanent
firewall-cmd --reload
firewall-cmd --query-port=8080/tcp
firewall-cmd --list-port
```

netns 调用本机 device IP 服务

```bash
ip addr 确定本机设备，信息为 ens33 192.168.211.131
# 调用本地异常，提示 curl: (7) Failed to connect to 192.168.211.131: Network is unreachable
sudo ip netns exec netns_dustin curl 192.168.211.131:8080

# 错误信息是因为不知道 how to route the 192.168.211.131 address
# if it can't find a suitable route for our request then direct the request to 10.0.0.10
# 添加路由后，上述 curl 正常
sudo ip netns exec netns_dustin ip route add default via 10.0.0.10

# 为什么添加上述 route 信息正常？是因为 10.0.0.10 位于 host network namespace；host network namespace 有 route 信息到 192.168.112.131
# netns_dustin --> veth_dustin --> 主机网络栈 --> ens33 --> 192.168.211.131
ip route list
default via 192.168.211.2 dev ens33 proto static metric 100
10.0.0.0/24 dev veth_dustin proto kernel scope link src 10.0.0.10
192.168.211.0/24 dev ens33 proto kernel scope link src 192.168.211.131 metric 100
```

## Access Internet From netns

```bash
ping 域名异常，ping: www.baidu.com: Name or service not known
sudo ip netns exec netns_dustin ping www.baidu.com -c 1

# ping IP 异常，From 10.0.0.10 icmp_seq = 1 Destination Host Prohibited
sudo ip netns exec netns_dustin ping 8.8.8.8
```

* 本机开启转发
  * `/proc/sys/net/ipv4/ip_forward` 1 表示转发
  * `echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward` 0 的话按照这个开启下
* 确认 `physical device` 
  * `ip address list` ，选择了 `ens33   192.168.211.131`
* 防火墙
  * virtual device to the physical device：`sudo iptables --append FORWARD --in-interface veth_dustin --out-interface ens33 --jump ACCEPT`
  * physical device to the virtual device：`sudo iptables --append FORWARD --in-interface ens33 --out-interface veth_dustin --jump ACCEPT`
  * 源地址转换：`sudo iptables --append POSTROUTING --table nat --out-interface ens33 --jump MASQUERADE`
  * 上述 `FORWARD` 如果使用 `--append` 参数追加到最后，后面测试会有问题，第五步有详细说明，默认的是信息如下
  
    `iptables --line-number -t filter -nvx -L FORWARD`
  
    19         20     1296 REJECT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            reject-with icmp-host-prohibited

按照上述操作后，ping IP 正常，ping 域名还是异常

## Config netns's resolv.conf

```bash
配置 DNS
sudo mkdir -p /etc/netns/netns_dustin
echo "nameserver 8.8.8.8" > /etc/netns/netns_dustin/resolv.conf
# 验证 DNS 配置
sudo ip netns exec netns_dustin cat /etc/resolv.conf
nameserver 8.8.8.8
```

但是 ping 域名还是异常，可能是由于主机的 `firewalld` 服务开启导致，放开 `53/udp` 尝试下

```bash
sudo ip netns exec netns_dustin ping www.baidu.com
ping: www.baidu.com: Name or service not known

# 放开 53/udp 以及 53/tcp
firewall-cmd --zone=public --add-port=53/udp --permanent
firewall-cmd --reload
firewall-cmd --query-port=53/udp
firewall-cmd --list-port
```

`firewall-cmd --reload` 执行后，把 `Access Internet From netns` 处操作的防火墙部分给刷掉了，所以再次执行下

```bash
查看
sudo iptables --line -L FORWARD
sudo iptables --line -t nat -L POSTROUTING
# 再次添加
sudo iptables --append FORWARD --in-interface veth_dustin --out-interface ens33 --jump ACCEPT
sudo iptables --append FORWARD --in-interface ens33 --out-interface veth_dustin --jump ACCEPT
sudo iptables --append POSTROUTING --table nat --out-interface ens33 --jump MASQUERADE
# 再次查看 sudo iptables --line -L FORWARD
Chain FORWARD (policy DROP)
......
20   ACCEPT     all  --  anywhere             anywhere
21   ACCEPT     all  --  anywhere             anywhere
# 再次查看 sudo iptables --line -t nat -L POSTROUTING
Chain POSTROUTING (policy ACCEPT)
........
6    MASQUERADE  all  --  anywhere             anywhere


# 再次验证 ping 域名，还是失败 ping: www.baidu.com: Name or service not known
sudo ip netns exec netns_dustin ping www.baidu.com
```

**不太确认此时还是无法 ping 域名失败原因，待定**

**后续抓包定位了，发现 ICMP 异常** ; 实际确定了通过主机测试 PING 正常：`ping -I 10.0.0.10 10.0.0.11`

```bash
确认 netns 的 PID
ip netns pids netns_dustin
2171
# 进入，执行 ip addr 确认
nsenter -n --target 2171
# netns 空间抓包
tcpdump -i any -w netns_ping_hosts.pcap
# 主机抓包
tcpdump -i any -w hosts_ping_hosts.pcap
# 主机访问 netns
sudo ip netns exec netns_dustin ping www.baidu.com

# 抓包异常信息
12	3.303467	10.0.0.10	10.0.0.11	ICMP	102	Destination unreachable (Host administratively prohibited)
```

后想到可能是 iptables 规则限制导致，不确定是哪个 chain 导致，通过以下命令一步步倒推

```bash
iptables -t filter -nvxL >01.filter
# 发下 curl 请求
sudo ip netns exec netns_dustin ping www.baidu.com
iptables -t filter -nvxL >02.filter

# diff 比较，内容比较多，看下来可能和下面这个比较接近
REJECT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            reject-with icmp-host-prohibited
# 再细分析，上述 REJECT 对应的 Chain 为 FORWARD
# iptables --line-number -t filter -nvx -L FORWARD
Chain FORWARD (policy DROP 0 packets, 0 bytes)
num      pkts      bytes target     prot opt in     out     source               destination
1          20     1296 DOCKER-ISOLATION-STAGE-1  all  --  *      *       0.0.0.0/0            0.0.0.0/0
2          20     1296 DOCKER-USER  all  --  *      *       0.0.0.0/0            0.0.0.0/0
3           0        0 ACCEPT     all  --  *      test_bridge  0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED
4           0        0 DOCKER     all  --  *      test_bridge  0.0.0.0/0            0.0.0.0/0
5           0        0 ACCEPT     all  --  test_bridge !test_bridge  0.0.0.0/0            0.0.0.0/0
6           0        0 ACCEPT     all  --  test_bridge test_bridge  0.0.0.0/0            0.0.0.0/0
7           0        0 ACCEPT     all  --  *      docker0  0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED
8           0        0 DOCKER     all  --  *      docker0  0.0.0.0/0            0.0.0.0/0
9           0        0 ACCEPT     all  --  docker0 !docker0  0.0.0.0/0            0.0.0.0/0
10          0        0 ACCEPT     all  --  docker0 docker0  0.0.0.0/0            0.0.0.0/0
11          0        0 ACCEPT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED
12          0        0 ACCEPT     all  --  lo     *       0.0.0.0/0            0.0.0.0/0
13         20     1296 FORWARD_direct  all  --  *      *       0.0.0.0/0            0.0.0.0/0
14         20     1296 FORWARD_IN_ZONES_SOURCE  all  --  *      *       0.0.0.0/0            0.0.0.0/0
15         20     1296 FORWARD_IN_ZONES  all  --  *      *       0.0.0.0/0            0.0.0.0/0
16         20     1296 FORWARD_OUT_ZONES_SOURCE  all  --  *      *       0.0.0.0/0            0.0.0.0/0
17         20     1296 FORWARD_OUT_ZONES  all  --  *      *       0.0.0.0/0            0.0.0.0/0
18          0        0 DROP       all  --  *      *       0.0.0.0/0            0.0.0.0/0            ctstate INVALID
19         20     1296 REJECT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            reject-with icmp-host-prohibited
20          0        0 ACCEPT     all  --  veth_dustin ens33   0.0.0.0/0            0.0.0.0/0
21          0        0 ACCEPT     all  --  ens33  veth_dustin  0.0.0.0/0            0.0.0.0/0
```

看下来可能是由于 20 和 21 的两个 ACCEPT 在 `REJECT     all` 之后导致该问题，按照下述再操作

重新处理 ACCEPT 的 iptables 规则，调试下看下结果

```bash
# 原命令
sudo iptables --append FORWARD --in-interface veth_dustin --out-interface ens33 --jump ACCEPT
sudo iptables --append FORWARD --in-interface ens33 --out-interface veth_dustin --jump ACCEPT

# 删除
iptables -t filter -D FORWARD 21
iptables -t filter -D FORWARD 20
# 确认
iptables --line-number -t filter -nvx -L FORWARD
# 在指定表的指定链的指定位置添加一条规则
iptables -t filter -I FORWARD 19 --in-interface veth_dustin --out-interface ens33 --jump ACCEPT
iptables -t filter -I FORWARD 19 --in-interface ens33 --out-interface veth_dustin --jump ACCEPT

# 按照理解，现在 ping 域名正常了，实际也确实正常了
sudo ip netns exec netns_dustin ping www.baidu.com
```

**由于调试的时候有个误操作，防火墙增加了 icmp-block ，导致一直 ping 异常的问题**

增加了下述命令，导致 ping IP 和域名的时候均提示：Destination Host Prohibited，下述 iptables 信息是忘记这个误操作的时候一层层倒退的，然后才想到这个问题

```bash
# 增加 icmp-block
sudo firewall-cmd --zone = public --add-icmp-block ={echo-request, echo-reply} --permanent
# 移除 icmp-block
sudo firewall-cmd --zone = public --remove-icmp-block ={echo-request, echo-reply} --permanent
# 核实icmp-block当前状态
sudo firewall-cmd --zone = public --list-icmp-blocks
```

倒推过程

```bash
可能是 Chain FWDI_public_deny (1 references)；该规则拒绝了来自任何源 IP 的 ICMP 流量（类型为 8，即 ping 请求）并使用 `icmp-host-prohibited` 拒绝响应；但是不确认为啥防火墙会有这个规则
Chain FORWARD (policy DROP 0 packets, 0 bytes)
15         55     4072 FORWARD_IN_ZONES  all  --  *      *       0.0.0.0/0            0.0.0.0/0

Chain FORWARD_IN_ZONES (1 references)
1           0        0 FWDI_public  all  --  ens36  *       0.0.0.0/0            0.0.0.0/0           [goto]

Chain FWDI_public (3 references)
2          55     4072 FWDI_public_deny  all  --  *      *       0.0.0.0/0            0.0.0.0/0

Chain FWDI_public_deny (1 references)
1          27     2268 REJECT     icmp --  *      *       0.0.0.0/0            0.0.0.0/0            icmptype 8 reject-with icmp-host-prohibited
```



## communicate across multiple network namespaces

```bash
sudo ip link add dev veth_leah type veth peer name veth_ns_leah
sudo ip link set dev veth_leah up
sudo ip address add 10.0.0.20/24 dev veth_leah
sudo ip netns add netns_leah
sudo ip link set dev veth_ns_leah netns netns_leah
sudo ip netns exec netns_leah ip link set dev lo up
sudo ip netns exec netns_leah ip link set dev veth_ns_leah up
sudo ip netns exec netns_leah ip address add 10.0.0.21/24 dev veth_ns_leah
sudo ip netns exec netns_leah ip route add default via 10.0.0.20
sudo ip netns exec netns_leah python3 -m http.server 8080
```

netns 之间网络互 ping，发现无法连接；本机 ping 之前的 netns 仍然正常

```bash
正常
ping 10.0.0.11 -c 1
# 主机 > netns_leah IP
ping 10.0.0.21 -c 1
# netns_dustin > netns_leah IP
sudo ip netns exec netns_dustin ping 10.0.0.21 -c 1
# netns_leah > netns_dustin IP
sudo ip netns exec netns_leah ping 10.0.0.11 -c 1
```

无法 ping 的原因如下：

IP 路由将使用第一个 `10.0.0.0/24` 路由进行任何匹配，这意味着所有 `10.0.0.0/24` 流量将通过 `veth_dustin` 接口定向。即使有时希望流量通过 `veth_leah` 接口定向。

```bash
ip route list
# 10.0.0.0/24 dev veth_leah proto kernel scope link src 10.0.0.20 这条路由其实是上述操作，自动增加的路由信息；实际测试下来执行下面三条命令，即会自动增加路由信息
# sudo ip link add dev veth_leah type veth peer name veth_ns_leah
# sudo ip link set dev veth_leah up
# sudo ip address add 10.0.0.20/24 dev veth_leah
default via 192.168.211.2 dev ens33 proto static metric 102
10.0.0.0/24 dev veth_dustin proto kernel scope link src 10.0.0.10
10.0.0.0/24 dev veth_leah proto kernel scope link src 10.0.0.20
```

可以通过设置不同区域的 IP 来解决，大致如下（下述操作可以不做，不影响本文档主流程）：

```bash
sudo ip link add dev veth_test_01 type veth peer name veth_ns_test_01
ip link set dev veth_test_01 up
ip address add 10.0.1.10/24 dev veth_test_01

# 再查看一下主机的 route，发现新增一个，和之前设置的 IP 不一样
ip route list
default via 192.168.211.2 dev ens33 proto static metric 102
10.0.0.0/24 dev veth_dustin proto kernel scope link src 10.0.0.10
......
10.0.1.0/24 dev veth_test_01 proto kernel scope link src 10.0.1.10

# 不光操作上述三个命令，还有给 netns 设置的默认路由，也得根据上述 IP 一并修改；下面的路由信息需要修改 IP，netns device IP 应该是可以不修改；可以简单理解为不同的 netns 相互不干涉
sudo ip netns exec netns_leah ip address add 10.0.0.21/24 dev veth_ns_leah
sudo ip netns exec netns_leah ip route add default via 10.0.1.10
```

按照上述操作，操作复杂且重复，后面通过 Linux virtual bridge devices 实现

## Create virtual bridge to join veth pairs

最终效果图如下

![image-20230816155731081](https://raw.githubusercontent.com/iYangcw/Photo/master/ip%20link%20bridge.png)

`bridge` 允许多个以太网和虚拟以太网设备相互通信

```bash
sudo ip link add dev bridge_home type bridge
sudo ip address add 10.0.0.1/24 dev bridge_home
sudo ip link set bridge_home up

# 验证，可以看到 bridge_home ，状态为 UNKNOWN [不是 UP ，但是看下来不影响]
ip link list
```

将主机的两个设备连接到 bridge：此时发现主机 ping 10.0.0.11 不通；有重新验证过，暂时原因不确定

```bash
sudo ip link set dev veth_dustin master bridge_home
sudo ip link set dev veth_leah master bridge_home
```

更改 netns 的默认路由，改成 use the `bridge_home` IP address

```bash
sudo ip netns exec netns_dustin ip route delete default via 10.0.0.10
sudo ip netns exec netns_dustin ip route add default via 10.0.0.1
sudo ip netns exec netns_leah ip route delete default via 10.0.0.20
sudo ip netns exec netns_leah ip route add default via 10.0.0.1
```

`10.0.0.0/24` 匹配的三条路由（ `veth_dustin` 、 `veth_leah` 和 `bridge_home` ）; 解决这个问题的简单方案是删除 `veth_dustin` 和 `veth_leah` 的 IP 地址；删除后，ping 10.0.0.11 正常了

```bash
ip route list

......
10.0.0.0/24 dev veth_dustin proto kernel scope link src 10.0.0.10
10.0.0.0/24 dev veth_leah proto kernel scope link src 10.0.0.20
10.0.0.0/24 dev bridge_home proto kernel scope link src 10.0.0.1
172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1

# 删除 IP
sudo ip address delete 10.0.0.10/24 dev veth_dustin
sudo ip address delete 10.0.0.20/24 dev veth_leah

# 删除 IP 后，本机 ping netns IP 正常，但是 netns 之间 ping 异常
# 正常
ping 10.0.0.11 -c 1
ping 10.0.0.21 -c 1
# 异常
sudo ip netns exec netns_dustin ping 10.0.0.21 -c 1
sudo ip netns exec netns_leah ping 10.0.0.11 -c 1
# netns 之间 ping 异常是因为目前 bridge_home 不能转发流量
# 目前 bridge_home 只能接受来自 veth_dustin 和 veth_leah 的流量
# 但是需要转发到 veth_leah 和 veth_dustin 的数据包都被 bridge_home  丢弃了
# 增加下述防火墙配置
sudo iptables --append FORWARD --in-interface bridge_home --out-interface bridge_home --jump ACCEPT
```

增加上述防火墙配置后，netns 之间验证 ping 和 curl ， ping 正常，curl 异常

```bash
sudo ip netns exec netns_dustin ping 10.0.0.21 -c 1
sudo ip netns exec netns_leah ping 10.0.0.11 -c 1
# 异常 curl: (7) Failed connect to 10.0.0.11: 8080; No route to host
sudo ip netns exec netns_dustin curl 10.0.0.21:8080
sudo ip netns exec netns_leah curl 10.0.0.11:8080
```

按照这个命令操作，curl 还是异常，推测是由于 append 追加到最后，前面有 REJECT all 导致；实际看下来应该确实是这个原因

```bash
sudo iptables --append FORWARD 
```

重新配置

```bash
查看
iptables --line-number -t filter -nvx -L FORWARD
......
19         14      914 ACCEPT     all  --  veth_dustin ens33   0.0.0.0/0            0.0.0.0/0
20          0        0 ACCEPT     all  --  ens33  veth_dustin  0.0.0.0/0            0.0.0.0/0
21         17     1040 REJECT     all  --  *      *       0.0.0.0/0            0.0.0.0/0            reject-with icmp-host-prohibited
22          0        0 ACCEPT     all  --  bridge_home bridge_home  0.0.0.0/0            0.0.0.0/0

# 删除
iptables -t filter -D FORWARD 22

# 确认
iptables --line-number -t filter -nvx -L FORWARD

# 在指定表的指定链的指定位置添加一条规则
iptables -t filter -I FORWARD 21 --in-interface bridge_home --out-interface bridge_home --jump ACCEPT
```

清理以前的规则

```bash
iptables --line-number -t filter -nxvL FORWARD
# 删除
iptables -t filter -D FORWARD 20
iptables -t filter -D FORWARD 19
```

netns 通过 bridge 访问外网不通，见下

```bash
sudo ip netns exec netns_dustin curl http://www.baidu.com
curl: (6) Could not resolve host: www.baidu.com; Unknown error

sudo ip netns exec netns_dustin ping 8.8.8.8
curl: (6) Could not resolve host: ping; Unknown error
```

增加下述操作，连接外网正常

```bash
# 查看，发现最后一步是 REJECT     all
iptables --line-number -t filter -nxvL FORWARD

# 增加，不要 append 追加
sudo iptables -I  FORWARD 20 --in-interface bridge_home --out-interface ens33 --jump ACCEPT
sudo iptables -I  FORWARD 21 --in-interface ens33 --out-interface bridge_home --jump ACCEPT

# 验证外网
sudo ip netns exec netns_dustin ping 8.8.8.8
sudo ip netns exec netns_dustin ping www.baidu.com
sudo ip netns exec netns_dustin curl http://www.baidu.com
```

## Clean UP

```bash
sudo ip link delete dev bridge_home
sudo ip link delete dev veth_dustin
sudo ip link delete dev veth_leah
sudo ip netns delete netns_dustin
sudo ip netns delete netns_leah
sudo iptables --delete FORWARD --in-interface bridge_home --out-interface ens33 --jump ACCEPT
sudo iptables --delete FORWARD --in-interface ens33 --out-interface bridge_home --jump ACCEPT
sudo iptables --delete POSTROUTING --table nat --out-interface ens33 --jump MASQUERADE
```
