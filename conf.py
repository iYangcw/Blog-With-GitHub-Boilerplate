# -*- coding: utf-8 -*-
"""博客构建配置文件
"""

# For Maverick
site_prefix = "/Blog-With-GitHub-Boilerplate/"
source_dir = "../src/"
build_dir = "../dist/"
index_page_size = 10
archives_page_size = 20
template = {
    "name": "Galileo",
    "type": "local",
    "path": "../Galileo"
}
enable_jsdelivr = {
    "enabled": False,
    "repo": ""
}

# 站点设置
site_name = "个人博客"
site_logo = "${static_prefix}logo.png"
site_build_date = "2019-12-18T16:51+08:00"
author = "Clover"
email = "test@email.com"
author_homepage = "https://iyangcw.github.io/Blog-With-GitHub-Boilerplate/"
description = "每天进步一点点"
key_words = ['Maverick', '熊猫小A', 'Galileo', 'blog']
language = 'zh-CN'
external_links = [
    {
        "name": "Maverick",
        "url": "https://github.com/AlanDecode/Maverick",
        "brief": "🏄‍ Go My Own Way."
    }
]
nav = [
    {
        "name": "首页",
        "url": "${site_prefix}",
        "target": "_self"
    },
    {
        "name": "归档",
        "url": "${site_prefix}archives/",
        "target": "_self"
    },
    {
        "name": "关于",
        "url": "${site_prefix}about/",
        "target": "_self"
    }
]

social_links = [
    {
        "name": "Twitter",
        "url": "https://twitter.com/iCloverLL",
        "icon": "gi gi-twitter"
    }
]

head_addon = r'''
<meta http-equiv="x-dns-prefetch-control" content="on">
<link rel="dns-prefetch" href="//cdn.jsdelivr.net" />
'''

footer_addon = ''

body_addon = ''
