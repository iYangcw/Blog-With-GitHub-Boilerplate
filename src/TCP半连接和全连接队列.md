---
layout: post
title: TCP半连接和全连接队列
slug: TCP
date: 2023-03-28 14:50
status: publish
author: Sai
categories: 
  - Maverick
tags:
  - TCP
excerpt: 关于TCP半连接和全连接队列问题
---

原始文档为以下三篇，根据相关文档进行的整理。

[从一次线上问题说起，详解 TCP 半连接队列、全连接队列](https://mp.weixin.qq.com/s/YpSlU1yaowTs-pF6R43hMw)

[TCP 半连接队列和全连接队列](https://xiaolincoding.com/network/3_tcp/tcp_queue.html#%E4%BB%80%E4%B9%88%E6%98%AF-tcp-%E5%8D%8A%E8%BF%9E%E6%8E%A5%E9%98%9F%E5%88%97%E5%92%8C%E5%85%A8%E8%BF%9E%E6%8E%A5%E9%98%9F%E5%88%97)

[详解 TCP 半连接队列与全连接队列](https://docs.google.com/spreadsheets/d/1uz_1QSTsegHr6qqmq0PG1Y6c6RLFz5Y2FfkCma9jTkY/edit?usp=sharing)

另外，Linux 源码请看 https://elixir.bootlin.com/linux/v3.10/source ，可以快速跳转。

全连接以及不开启cookie的半连接，Linux 3.10.0 的结果能分析出来，但是开了cookie的半连接，试验数据一直对不上。

由于 C 语言 已经忘记了，C 语言源码分析是在引用链接结合 Chatgpt 进行分析理解的，部分实在分析不了，拾人牙慧。



# 1、基础信息

## 1.1、服务端和客户端信息

本试验的 Linux 内核版本：3.10.0，以下均是基于此分析。

## 1.2、ss 命令

ss 利用到了 TCP 协议栈中的 tcp_diag（见 1.4 的分析）。tcp_diag 是一个用于分析统计的模块，可以获得 Linux 内核中第一手的信息，这就确保了 ss 的快捷高效。当然，如果你的系统中没有 tcp_diag，ss 也可以正常运行，只是效率会变得稍慢。

在「LISTEN 状态」时，`Recv-Q/Send-Q` 表示的含义如下：

* Recv-Q：当前全连接队列的大小，也就是当前已完成三次握手并等待服务端 `accept()` 的 TCP 连接；

- Send-Q：当前全连接最大队列长度，下面的输出结果说明监听 8088 端口的 TCP 服务，最大全连接长度为 128；

```bash
# -l , --listening 显示监听状态的套接字（sockets）
# -n , --numeric   不解析服务名称
# -t , --tcp       仅显示 TCP套接字（sockets）
$ ss -lnt
State       Recv-Q Send-Q            Local Address:Port                           Peer Address:Port
LISTEN      6      128                        [::]:8888                                   [::]:*     
```

在「非 LISTEN 状态」时，`Recv-Q/Send-Q` 表示的含义如下：

- Recv-Q：已收到但未被应用进程读取的字节数；
- Send-Q：已发送但未收到确认的字节数；

```bash
# -n , --numeric   不解析服务名称
# -t , --tcp       仅显示 TCP套接字（sockets）
$ ss -nt
State       Recv-Q Send-Q            Local Address:Port                           Peer Address:Port
ESTAB       0      36               192.168.56.101:22                             192.168.56.1:12656
CLOSE-WAIT  12     0       [::ffff:192.168.56.101]:8888                [::ffff:192.168.56.100]:34204 
```

## 1.3、netstat 命令

通过 `netstat -s` 命令可以查看 TCP 半连接队列、全连接队列的溢出情况

下面输出的数值是累计值，分别表示有多少 TCP socket 链接因为全连接队列、半连接队列满了而被丢弃

注意 **times** 是次数，不是时间的意思。

**在排查线上问题时，如果一段时间内相关数值一直在上升，则表明半连接队列、全连接队列有溢出情况**

```bash
$ netstat -s |grep -i listen
    911 times the listen queue of a socket overflowed
    911 SYNs to LISTEN sockets dropped
```

## 1.4、tcp_diag.c  分析

不同内核版本的 tcp_diag.c 的代码是不一样的，本试验的 Linux 内核版本：3.10.0

`ss` 命令获取的 `Recv-Q/Send-Q` 在「LISTEN 状态」和「非 LISTEN 状态」所表达的含义是不同的，见3.10.0的内核代码。

```c
// https://elixir.bootlin.com/linux/v3.10/source/net/ipv4/tcp_diag.c
static void tcp_diag_get_info(struct sock *sk, struct inet_diag_msg *r,
			      void *_info)
{
	const struct tcp_sock *tp = tcp_sk(sk);
	struct tcp_info *info = _info;
	// 如果 TCP 连接状态是 LISTEN 时
	if (sk->sk_state == TCP_LISTEN) {
        // 当前全连接队列的大小
		r->idiag_rqueue = sk->sk_ack_backlog;
        // 当前全连接的最大队列长度
		r->idiag_wqueue = sk->sk_max_ack_backlog;
	}
    // 如果 TCP 连接状态不是 LISTEN 时
    else {
        // 已收到但未被应用进程读取的字节数
		r->idiag_rqueue = max_t(int, tp->rcv_nxt - tp->copied_seq, 0);
        // 已发送但未收到确认的字节数
		r->idiag_wqueue = tp->write_seq - tp->snd_una;
	}
	if (info != NULL)
		tcp_get_info(sk, info);
}
```

## 1.5、Accept Queue：全连接队列的结论

Accept Queue：全连接队列

最大队列为：`min(backlog, net.core.somaxconn)`

校验 Accept Queue 是否满的逻辑如下（ 注意大于号才返回ture，即最终可存储 **socket 数目会加1**）：

`return sk->sk_ack_backlog > sk->sk_max_ack_backlog`

## 1.6、SYN Queue：半连接队列的结论

半连接的逻辑比较复杂，算出最大连接后，还有其他逻辑进行判断。实际测试下来的情况，不开启 cookie 的结果和结论能对的上，但是开启 cookie 后，测试的结果对不上【**以后再进行分析，目前一直无法测试到结果**】

**不开启cookie的结论如下**

1、半连接最大连接 > 0.75\*tcp_max_syn_backlog，则 Drop SYN临界值为 0.75\*tcp_max_syn_backlog +1【+1是因为判断条件是大于号，另外0.75乘法后的结果不确定是否是四舍五入还是向上取整，但是从实际结果来看小点数如果是 0.5 结果是按照 1 来计算】

2、半连接最大连接 <= 0.75*tcp_max_syn_backlog，则 Drop SYN临界值为 半连接最大连接

【tcp_v4_conn_request 函数的第三处判断，按照代码判断 等于号 应是上述 2 的结论，但是由于 测试中的 256除以0.75 不是整数，无法进一步确认等于号 =】

**开启cookie的结论如下：**

按照网上说的，应是当半连接队列长度 > 全连接队列最大长度时，就会触发 DROP SYN 请求。但是目前我测试下来，SYN_RECV 的数量无法达到上限，无法验证结果。【**后续再研究，目前测试一直无法得出啥结论**】



### 1.6.1、半连接队列最大长度控制

由于C语言已忘记，计算公式无法确认，以下信息为借鉴。

很多博文中说半连接队列最大长度由 /proc/sys/net/ipv4/tcp_max_syn_backlog 参数指定，**实际上只有在 linux 内核版本小于 2.6.20 时，半连接队列才等于 backlog 的大小**。

```c
// max_qlen_log - log_2 of maximal queued SYNs/REQUESTs
// 也就是说 最大半连接队列 等于 2 的 max_qlen_log 次方
nr_table_entries = min_t(u32, nr_table_entries, sysctl_max_syn_backlog);
nr_table_entries = max_t(u32, nr_table_entries, 8);
nr_table_entries = roundup_pow_of_two(nr_table_entries + 1);
//向上取满足2的指数倍的整数

for (lopt->max_qlen_log = 3;
     (1 << lopt->max_qlen_log) < nr_table_entries;
     lopt->max_qlen_log++);

//大体计算过程如下
backlog = min(somaxconn, backlog)
nr_table_entries = backlog
nr_table_entries = min(backlog, sysctl_max_syn_backlog)
nr_table_entries = max(nr_table_entries, 8)
// roundup_pow_of_two: 将参数向上取整到最小的 2^n
// 注意这里存在一个 +1
nr_table_entries = roundup_pow_of_two(nr_table_entries + 1)
max_qlen_log = max(3, log2(nr_table_entries))
max_queue_length = 2^max_qlen_log
```

sysctl_max_syn_backlog 即内核参数 net.ipv4.tcp_max_syn_backlog （3.10.0 代码默认值是256，但是系统参数是128）

2^max_qlen_log^ 也就是最大情况为 2^log2{nr_table_entries}^ ,也就是 nr_table_entries 的值；最小为 8

有一点绕，不过运算都很简单，半连接队列的长度实际上由三个参数决定

- `listen` 时传入的 backlog
- `/proc/sys/net/ipv4/tcp_max_syn_backlog`
- `/proc/sys/net/core/somaxconn`

```bash
# 相关操作命令
# backlog，用的 Golang 测试，在 Golang 中，listen 的 backlog 参数使用的是 /proc/sys/net/core/somaxconn 文档中的值
sudo sysctl -w net.core.somaxconn=128
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=512
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

### 1.6.2、判断是否 Drop SYN 请求

当 Client 端向 Server 端发送 SYN 报文后，Server 端会将该 socket 连接存储到半连接队列(SYN Queue)，如果 Server 端判断半连接队列满了则会将连接 Drop 丢弃。

那么 Server 端是如何判断半连接队列是否满的呢？除了上面一小节提到的半连接队列最大长度控制外，还和 /proc/sys/net/ipv4/tcp_syncookies 参数有关。(tcp_syncookies 的作用是为了防止 SYN Flood 攻击的)

![](https://raw.githubusercontent.com/iYangcw/Photo/master/sys_length_calc.png)

**注意：第一个判断条件 「当前半连接队列是否已超过半连接队列最大长度」在不同内核版本中的判断不一样，引用文章的 Linux 4.19.91 内核判断的是当前半连接队列长度是否 >= 全连接队列最大长度，但是本文实验的 Linux 3.10.0 正好满足该截图**

实际测试的结果如下，按照cookie是否开启进行测试验证。

[Google 表格链接](https://docs.google.com/spreadsheets/d/1uz_1QSTsegHr6qqmq0PG1Y6c6RLFz5Y2FfkCma9jTkY/edit?usp=sharing) ：Sheet里面已经写好了部分计算公式

**没开启cookie的结果如下：**

Linux 3.10.0 的测试结果如下：

字段 a = max(min(backlog,somaxconn,sysctl_max_sys_backlog),8)

半队列最大长度等于 `roundup_pow_of_two(a+1)`

由于是 `Golang` 测试，backlog 等于 somaxconn

| somaxconn | tcp_max_syn_backlog | tcp_max_syn_backlog * 0.75 | a | 半队列Max | 全队列Max | Drop SYN 临界值 |
| --------- | ------------------- | -------------------------- | ------------------------------------------------------ | -------------- | -------------- | -------------------- |
| 1024      | 128                 | 96                         | 128                                                    | 256            | 1024           | 96+1=97              |
| 128       | 118                 | 88.5                       | 118                                                    | 128            | 128            | 88.5+1=90            |
| 128       | 108                 | 81                         | 108                                                    | 128            | 128            | 81+1=82              |
| 3         | 2                   | 1.5                        | 8                                                      | 16             | 3              | 1.5+1=3              |
| 128       | 512                 | 384                        | 128                                                    | 256            | 128            | 256                  |
| 128       | 342                 | 256.5                      | 128                                                    | 256            | 128            | 256                  |
| 128       | 340                 | 255                        | 128                                                    | 256            | 128            | 255+1=256            |
| 128       | 338                 | 253.5                      | 128                                                    | 256            | 128            | 253.5+1=255          |

```bash
实验一：syncookies=0，somaxconn=1024，backlog=1024，tcp_max_syn_backlog=128
计算出的半连接队列最大长度为 256
当半连接队列长度增长至 96+1 后，后续 SYN 请求就会触发 Drop
# 客户端进行压测
hping3 -S -p 8888 --flood 192.168.56.101
# 服务端每秒获取 SYN_RECV 连接数，结果稳定在 97
while true;do echo $(sudo netstat -nat | grep :8888 | grep 'SYN_RECV'  | wc -l);sleep 1;done
while true;do echo $(ss -n state syn-recv sport = :8888 | wc -l);sleep 1;done

其他的参数试验见表格结果。
```

**开启cookie的结果如下：**

一直无法复现网上结果，待定！



## 1.7、tcp_v4_conn_request 源码

内核版本：3.10.0

TCP 第一次握手：收到 SYN 包 的 Linux 内核代码如下，下文缩减了大量代码，只保留了 TCP 办连接队列溢出的处理逻辑：

* 半连接队列满了，且 isn 为 0，且没有开启 tcp_syncookies，则丢弃连接
* 全连接队列满了，且没有重传的包的连接请求多余1个，则会丢弃
* 禁用SYN Cookie机制，并且队列中剩余的连接请求数量小于最大队列长度的四分之一，同时`tcp_peer_is_proven`函数返回`false`（表明当前目标端无法被证明是存活的），那么连接请求将被拒绝并释放。

```c
// https://elixir.bootlin.com/linux/v3.10/source/net/ipv4/tcp_ipv4.c

int tcp_v4_conn_request(struct sock *sk, struct sk_buff *skb)
{
	struct tcp_options_received tmp_opt;
	struct request_sock *req;
	struct inet_request_sock *ireq;
	struct tcp_sock *tp = tcp_sk(sk);
	struct dst_entry *dst = NULL;
	__be32 saddr = ip_hdr(skb)->saddr;
	__be32 daddr = ip_hdr(skb)->daddr;
	__u32 isn = TCP_SKB_CB(skb)->when;
	bool want_cookie = false;
	struct flowi4 fl4;
	struct tcp_fastopen_cookie foc = { .len = -1 };
	struct tcp_fastopen_cookie valid_foc = { .len = -1 };
	struct sk_buff *skb_synack;
	int do_fastopen;

	/* TW buckets are converted to open requests without
	 * limitations, they conserve resources and peer is
	 * evidently real one.
	 */
	// 1、半连接队列满了，且 isn 为 0，且没有开启 tcp_syncookies，则丢弃连接
	if (inet_csk_reqsk_queue_is_full(sk) && !isn) {
		want_cookie = tcp_syn_flood_action(sk, skb, "TCP");
		if (!want_cookie)
			goto drop;
	}

	/* Accept backlog is full. If we have already queued enough
	 * of warm entries in syn queue, drop request. It is better than
	 * clogging syn queue with openreqs with exponentially increasing
	 * timeout.
	 */
    // 若此时 accept queue 也已满，并且 qlen_young 的值大于 1（即保存在 SYN queue 中未进行 SYN,ACK 重传的连接超过 1 个）
    // 则直接丢弃当前 SYN 包（相当于针对 SYN 进行了速率限制）
	if (sk_acceptq_is_full(sk) && inet_csk_reqsk_queue_young(sk) > 1) {
		NET_INC_STATS_BH(sock_net(sk), LINUX_MIB_LISTENOVERFLOWS);
		goto drop;
	}
    
    
     // 大体意思就是开启了 sysctl_tcp_syncookies ，则 want_cookie 为 true   
	if (want_cookie) {
		isn = cookie_v4_init_sequence(sk, skb, &req->mss);
		req->cookie_ts = tmp_opt.tstamp_ok;
	} else if (!isn) {
		/* VJ's idea. We save last timestamp seen
		 * from the destination in peer table, when entering
		 * state TIME-WAIT, and check against it before
		 * accepting new connection request.
		 *
		 * If "isn" is not zero, this request hit alive
		 * timewait bucket, so that all the necessary checks
		 * are made in the function processing timewait state.
		 */
		if (tmp_opt.saw_tstamp &&
		    tcp_death_row.sysctl_tw_recycle &&
		    (dst = inet_csk_route_req(sk, &fl4, req)) != NULL &&
		    fl4.daddr == saddr) {
			if (!tcp_peer_is_proven(req, dst, true)) {
				NET_INC_STATS_BH(sock_net(sk), LINUX_MIB_PAWSPASSIVEREJECTED);
				goto drop_and_release;
			}
		}
		/* Kill the following clause, if you dislike this way. */
        // 3--不开启cookie的情况，inet_csk_reqsk_queue_len为当前队列大小
		else if (!sysctl_tcp_syncookies &&
			 (sysctl_max_syn_backlog - inet_csk_reqsk_queue_len(sk) <
			  (sysctl_max_syn_backlog >> 2)) &&
			 !tcp_peer_is_proven(req, dst, false)) {
			/* Without syncookies last quarter of
			 * backlog is filled with destinations,
			 * proven to be alive.
			 * It means that we continue to communicate
			 * to destinations, already remembered
			 * to the moment of synflood.
			 */
			LIMIT_NETDEBUG(KERN_DEBUG pr_fmt("drop open request from %pI4/%u\n"),
				       &saddr, ntohs(tcp_hdr(skb)->source));
			goto drop_and_release;
		}

		isn = tcp_v4_init_sequence(skb);
	}
	tcp_rsk(req)->snt_isn = isn;
}
```

## 1.8、SYN 和 ACCEPT 连接图

![](https://raw.githubusercontent.com/iYangcw/Photo/master/SYN%20Queue%20and%20Accept%20Queue.png)



`TCP`连接创建时，客户端通过发送`SYN`报文发起向处于监听状态的服务器发起连接，服务器为该连接分配一定的资源，并发送`SYN+ACK`报文。对服务器来说，此时该连接的状态称为`半连接`(`Half-Open`)，而当其之后收到客户端回复的`ACK`报文后，连接才算创建完成。在这个过程中，如果服务器一直没有收到`ACK`报文(比如在链路中丢失了)，服务器会在超时后重传`SYN+ACK`。



# 2、全连接队列实战

## 2.1、结论

**TCP 全连接队列的最大值取决于 somaxconn 和 backlog 之间的最小值，也就是 min(somaxconn, backlog)**

**（准确点说应该是根据内核版本来确认代码里面的判断逻辑，目前暂时认为所有 Linux 的版本都是上面的结论）**

- `somaxconn` 是 Linux 内核的参数，可以通过 `/proc/sys/net/core/somaxconn` 来设置其值，默认值根据版本来，是128 或者 4096。

  ```bash
  # https://man7.org/linux/man-pages/man2/listen.2.html
  Since Linux 5.4, the default in this file is 4096; in
         earlier kernels, the default value is 128.  In kernels before
         2.4.25, this limit was a hard coded value, SOMAXCONN, with the
         value 128.
  ```

- `backlog` 是 `listen(int sockfd, int backlog)` 函数中的 backlog 大小

  <Unix 网络编程>将其描述为**已完成的连接队列**(`ESTABLISHED`)与**未完成连接队列**(`SYN_RCVD`)之和的上限

```c
// https://elixir.bootlin.com/linux/v3.10/source/net/socket.c
SYSCALL_DEFINE2(listen, int, fd, int, backlog)
{
	struct socket *sock;
	int err, fput_needed;
	int somaxconn;

	sock = sockfd_lookup_light(fd, &err, &fput_needed);
	if (sock) {
		somaxconn = sock_net(sock->sk)->core.sysctl_somaxconn;
		if ((unsigned int)backlog > somaxconn)
			backlog = somaxconn;

		err = security_socket_listen(sock, backlog);
		if (!err)
			err = sock->ops->listen(sock, backlog);

		fput_light(sock->file, fput_needed);
	}
	return err;
}
```

## 2.2、测试方案

* 通过 **wrk** 对服务端的 **nginx** 发起压测来查看当前队列 **Recv-Q** 使用情况
* 通过 **go** 代码发起 **http** 请求：只负责 Listen 对应端口，而不执行 accept() TCP 连接，使TCP全连接队列溢出，抓包进行分析

## 2.3、wrk 操作过程

系统参数配置信息如下

```bash
# nginx 配置文件的backlog，默认为511，另外如果修改的话，nginx需要重启，reload 看下来 backlog 是不生效的
backlog = 511
sysctl -w net.core.somaxconn=128
# cookies 开启关闭都测试下
sysctl -w net.ipv4.tcp_syncookies=0
sysctl -w net.ipv4.tcp_syncookies=0
# net.ipv4.tcp_max_syn_backlog=512 默认值，没有修改
# tcp_max_syn_backlog 不动，3.10 内核上默认是 512，backlog 和 max_syn_backlog 应该是有一定关系的，应该不能超过 max_syn_backlog
```

启动 nginx 服务后，通过 ss 确认 Send-Q 大小（按照 min(128,511) 原则，应是 128）

```bash
# nginx 的端口为 80
$ ss -lnt
State       Recv-Q Send-Q            Local Address:Port                           Peer Address:Port
LISTEN      0      128                           *:80                                        *:*    
```

客户端压测过程：

```bash
# 客户端发起 wrk 压测
# -t 20 	表示 20 个线程（建议调大，否则有可能服务端能处理过来，Recv-Q 不会超标）
# -c 30000	表示 3 万个连接
# -d 60s	表示持续压测 60 秒
$ ulimit -n 1000000 # 临时调大点，否则有可能提示 Too many open files
$ wrk -t 20 -c 30000 -d 60s http://192.168.56.101:80
Running 1m test @ http://192.168.56.101:80
  20 threads and 30000 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   278.14ms  197.13ms   1.99s    83.94%
    Req/Sec   131.67    207.18     1.68k    90.59%
  43677 requests in 1.01m, 55.90MB read
  Socket errors: connect 0, read 1022705, write 0, timeout 1369
Requests/sec:    722.80
Transfer/sec:      0.93MB
```

服务端相关信息：`tcp_syncookies` 关闭，发现 Recv-Q 很快就到达 **129**，且几乎持续维持在这个值；反之如果开启了，Recv-Q 也达到过 **129**，但是波动很大。从常识上也能理解到开启 cookie 了有存在复用，所以当前连接队列会小一点。

```bash
# 间隔一秒，定时检测 80 端口的 socket 连接信息
$ while true;do echo "当前时间:"$(date +%T);ss -lnt |grep -E 'Send-Q|80';sleep 1;done
当前时间:05:23:55
State      Recv-Q Send-Q Local Address:Port               Peer Address:Port              
LISTEN     61     128          *:80                       *:*                  
当前时间:05:23:56
State      Recv-Q Send-Q Local Address:Port               Peer Address:Port              
LISTEN     129    128          *:80                       *:*                  
```

**且注意下，Recv-Q 的最大值就是 【全连接队列最大值 + 1】**

该现象是因为**内核在判断全连接是否满**的情况下，使用的是 > 而非 >= 。

```c
// https://github.com/torvalds/linux/blob/v3.10/include/net/sock.h
// 检测全连接队列是否已满的函数
static inline bool sk_acceptq_is_full(const struct sock *sk)
{
    // sk_ack_backlog：当前全连接队列的大小
    // sk_max_ack_backlog：当前全连接的最大队列长度
	return sk->sk_ack_backlog > sk->sk_max_ack_backlog;
}
```

**当超过了 TCP 最大全连接队列，服务端则会丢掉后续进来的 TCP 连接**，丢掉的 TCP 连接的个数会被统计起来，我们可以使用 netstat -s 命令来查看：注意下，

```bash
$ netstat -s | grep -i listen
    180233 times the listen queue of a socket overflowed
    594579 SYNs to LISTEN sockets dropped
```



## 2.4、go 抓包操作过程

### 2.4.1、go 代码

为了方便实验，将 **server** 端的 **somaxconn** 全连接队列最大长度更新为 5，另外启动 go 服务后请通过 ss -lnt 确认是否生效

`sudo sysctl -w net.core.somaxconn=128`

`ss -lnt |grep -E 'Send-Q|8888'`

server 端

```go
// 只负责 Listen 对应端口而不执行 accept() TCP 连接
// server.go
// go build server.go
// ./server
package main

import (
  "log"
  "net"
  "time"
)

func main() {
  l, err := net.Listen("tcp", ":8888")
  if err != nil {
    log.Printf("failed to listen due to %v", err)
  }
  defer l.Close()
  log.Println("listen :8888 success")

  for {
    time.Sleep(time.Second * 100)
  }
}
```

client 代码

```go
// client 端并发请求 10 次 server 端，成功创建 tcp 连接后向 server 端发送数据
package main

import (
  "context"
  "log"
  "net"
  "os"
  "os/signal"
  "sync"
  "syscall"
  "time"
)

var wg sync.WaitGroup

func establishConn(ctx context.Context, i int) {
  defer wg.Done()
  conn, err := net.DialTimeout("tcp", "192.168.56.101:8888", time.Second*5)
  if err != nil {
    log.Printf("%d, dial error: %v", i, err)
    return
  }
  log.Printf("%d, dial success", i)
  _, err = conn.Write([]byte("hello world"))
  if err != nil {
    log.Printf("%d, send error: %v", i, err)
    return
  }
  select {
  case <-ctx.Done():
    log.Printf("%d, dail close", i)
  }
}

func main() {
  ctx, cancel := context.WithCancel(context.Background())
  for i := 0; i < 10; i++ {
    wg.Add(1)
    go establishConn(ctx, i)
  }

  go func() {
    sc := make(chan os.Signal, 1)
    signal.Notify(sc, syscall.SIGINT)
    select {
    case <-sc:
      cancel()
    }
  }()
```

### 2.4.2、操作过程

服务端启动程序后，客户端按照以下命令开始抓包后，再执行客户端程序

`sudo  tshark -Eheader=y -l -f "tcp port 8888" -i any -w client_to_server.pcap`

### 2.4.3、抓包结果分析

第三步的抓包结果不是每次必现

### 2.4.4、抓包结果-01

正常连接

![](https://raw.githubusercontent.com/iYangcw/Photo/master/connect_01.png)

### 2.4.5、抓包结果-02

![](https://raw.githubusercontent.com/iYangcw/Photo/master/connect_02.png)

Client 认为成功与 Server 端创建 tcp socket 连接，后续发送数据失败，持续 RETRY;Server 端认为 TCP 连接未创建，一直在发送SYN+ACK。

Server 端为什么一直在 RETRY 发送 `SYN+ACK`? Server 端不是已经收到了 Client 端的 ACK 确认了吗?

上述情况是由于 Server 端 socket 连接进入了半连接队列，在收到 Client 端 ACK 后，本应将 socket 连接存储到全连接队列，但是全连接队列已满，所以 Server 端 DROP 了该 ACK 请求。

Server 端一直在 RETRY 发送 `SYN+ACK`，是因为 DROP 了 client 端的 ACK 请求，所以 socket 连接仍旧在半连接队列中，等待 Client 端回复 ACK。

全连接队列满 DROP 请求是默认行为，可以通过设置 `/proc/sys/net/ipv4/tcp_abort_on_overflow` 使 Server 端在全连接队列满时，向 Client 端发送 RST 报文。

`tcp_abort_on_overflow` 有两种可选值：

- 0：如果全连接队列满了，Server 端 DROP Client 端回复的 ACK 【默认值】
- 1：如果全连接队列满了，Server 端向 Client 端发送 RST 报文，终止 TCP socket 链接

### 2.4.6、抓包结果-03

![](https://raw.githubusercontent.com/iYangcw/Photo/master/connect_03.png)

Client 向 Server 发送 SYN 未得到相应，一直在 RETRY。

需要结合半连接队列来分析，结论如下

1、开启了 `/proc/sys/net/ipv4/tcp_syncookies` 功能

2、全连接队列满了

# 3、半连接队列实战

## 3.1、结论

见 1.6 结论

## 3.2、内核代码分析

见1.7

### 3.2.1、半连接代码

代码流程大致流程就是：

半连接队列满了，且 ISN 为0，则判断是否开启 cookie，如果开启了cookie 走其他逻辑，如果没开启cookie，则丢弃该包

大白话，个人理解如下（SYN洪水攻击的逻辑）：

这一部分应该是 SYN 洪水攻击避免的实现逻辑，SYN洪水攻击中，攻击者通常会将TCP握手过程中的调用方序列号（ISN）置为0，目的在于混淆目标主机，并使其无法正确地处理TCP连接请求。

所以方法的逻辑是 `!isn`，如果队列已满，且有 ISN=0 的情况，则走到 want_cookie 的逻辑；

如果不需要进行 cookie 验证，则直接跳转到 drop，即丢弃该数据包。

```c
// 半连接队列满了，且 isn 为 0：即没有生成初始序列号
if (inet_csk_reqsk_queue_is_full(sk) && !isn) {
	want_cookie = tcp_syn_flood_action(sk, skb, "TCP");
	if (!want_cookie)
		goto drop;
}

/*
	第一处分析
	https://elixir.bootlin.com/linux/v3.10/source/include/net/inet_connection_sock.h#L297
	该函数主要通过调用reqsk_queue_is_full函数来判断TCP套接字的请求队列是否已满，函数输入参数为TCP套接字sk.
	在函数实现中，首先调用inet_csk函数获取TCP套接字的传输控制块，并通过icsk_accept_queue访问请求队列，从而判断该请求队列是否已满.
	队列已满,函数  返回 1;
	队列未满,函数  返回 0.
*/
static inline int inet_csk_reqsk_queue_is_full(const struct sock *sk)
{
	return reqsk_queue_is_full(&inet_csk(sk)->icsk_accept_queue);
}

static inline int reqsk_queue_is_full(const struct request_sock_queue *queue)
{
    /*
     C语言不懂，查阅资料说是这段代码的意思是
	 用于检查一个请求队列是否已满。该函数的作用是判断指定的请求队列是否已经达到了最大队列长度，如果达到最大长度则返回1，否则返回0。
    */
	return queue->listen_opt->qlen >> queue->listen_opt->max_qlen_log;
}


/*
	第二处分析：!isn，能正常往该函数继续往下走，也就是 isn 为 0
	一个TCP连接的ISN被设置为0，这意味着这个连接没有已知的初始序列号。这意味着发送方和接收方都将从初始位置开始传输数据。
	
	__u32 isn = TCP_SKB_CB(skb)->when;
	这段代码是从skb中获取TCP协议块的发送时间戳，并将其赋值给变量isn。
	
	__u32：unsigned 32-bit integer（无符号32位整数）
	TCP_SKB_CB(skb)是一个宏定义，用于获取指向TCP协议块头部的指针，这里使用when字段来表示该TCP协议块的发送时间戳。
*/


/*
	第三处分析：tcp_syn_flood_action
	https://elixir.bootlin.com/linux/v3.10/source/net/ipv4/tcp_ipv4.c
	Return true if a syncookie should be sent
	大体意思就是开启了 sysctl_tcp_syncookies ，则 want_cookie 为 true
	这个参数默认值为1，可以通过修改 /proc/sys/net/ipv4/tcp_syncookies 文件或者使用sysctl命令进行修改
*/
```



### 3.2.2、全连接代码

若此时 accept queue 也已满，并且 qlen_young 的值大于 1（即保存在 SYN queue 中未进行 SYN,ACK 重传的连接超过 1 个），则直接丢弃当前 SYN 包（相当于针对 SYN 进行了速率限制）

```c
if (sk_acceptq_is_full(sk) && inet_csk_reqsk_queue_young(sk) > 1) {
	NET_INC_STATS_BH(sock_net(sk), LINUX_MIB_LISTENOVERFLOWS);
	goto drop;
}
```

第一处代码分析如下

```c
/*
	https://elixir.bootlin.com/linux/v3.10/source/include/net/sock.h#L723
	如果TCP连接请求接收队列已满，则返回true。
	通过检查 backlog 和 sk_max_ack_backlog 字段的值，来决定TCP连接请求队列是否已满。
	sk_ack_backlog	当前全连接队列大小
	sk_max_ack_backlog	全连接队列最大值 min(somaxconn,backlog)
*/
static inline bool sk_acceptq_is_full(const struct sock *sk)
{
	return sk->sk_ack_backlog > sk->sk_max_ack_backlog;
}

//

```

第二处代码分析如下

```c
/*
	https://elixir.bootlin.com/linux/v3.10/source/include/net/inet_connection_sock.h#L292
	看的不是很明白，qlen_young 没理解意思，机械理解成 保存在 SYN queue 中未进行 SYN,ACK 重传的连接
*/
static inline int inet_csk_reqsk_queue_young(const struct sock *sk)
{
	return reqsk_queue_len_young(&inet_csk(sk)->icsk_accept_queue);
}
// https://elixir.bootlin.com/linux/v3.10/source/include/net/request_sock.h#L252
static inline int reqsk_queue_len_young(const struct request_sock_queue *queue)
{
	return queue->listen_opt->qlen_young;
}

/** struct listen_sock - listen state
 *
 * @max_qlen_log - log_2 of maximal queued SYNs/REQUESTs
 */
struct listen_sock {
	u8			max_qlen_log;
	u8			synflood_warned;
	/* 2 bytes hole, try to use */
	int			qlen;
	int			qlen_young;
	int			clock_hand;
	u32			hash_rnd;
	u32			nr_table_entries;
	struct request_sock	*syn_table[0];
};
```

### 3.3.3、请求队列溢出时的逻辑

代码展示了Linux内核中在TCP连接请求队列溢出时的逻辑

```c
		else if (!sysctl_tcp_syncookies &&
			 (sysctl_max_syn_backlog - inet_csk_reqsk_queue_len(sk) <
			  (sysctl_max_syn_backlog >> 2)) &&
			 !tcp_peer_is_proven(req, dst, false)) {
			/* Without syncookies last quarter of
			 * backlog is filled with destinations,
			 * proven to be alive.
			 * It means that we continue to communicate
			 * to destinations, already remembered
			 * to the moment of synflood.
			 */
			LIMIT_NETDEBUG(KERN_DEBUG pr_fmt("drop open request from %pI4/%u\n"),
				       &saddr, ntohs(tcp_hdr(skb)->source));
			goto drop_and_release;
		}
```



# 4、参考文档

从一次线上问题说起，详解 TCP 半连接队列、全连接队列

- https://mp.weixin.qq.com/s/YpSlU1yaowTs-pF6R43hMw

深入浅出TCP中的SYN-Cookies

- https://segmentfault.com/a/1190000019292140

TCP 半连接队列和全连接队列

* https://xiaolincoding.com/network/3_tcp/tcp_queue.html#%E4%BB%80%E4%B9%88%E6%98%AF-tcp-%E5%8D%8A%E8%BF%9E%E6%8E%A5%E9%98%9F%E5%88%97%E5%92%8C%E5%85%A8%E8%BF%9E%E6%8E%A5%E9%98%9F%E5%88%97

详解 TCP 半连接队列与全连接队列

* https://wgzhao.github.io/notes/troubleshooting/deep-in-tcp-connect/

从 Linux 源码看 Socket (TCP) 的 listen 及连接队列

* https://my.oschina.net/alchemystar/blog/4672630

详解 TCP 半连接队列与全连接队列

* https://wgzhao.github.io/notes/troubleshooting/deep-in-tcp-connect/

[内核源码] 网络协议栈 - listen (tcp)

* https://wenfh2020.com/2021/07/21/kernel-sys-listen/

socket API 实现

* http://blog.guorongfei.com/tags/socket/

SYN packet handling in the wild

* https://blog.cloudflare.com/syn-packet-handling-in-the-wild/

