#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出入库管理系统 - Web 版
基于 Flask，单文件部署，监听 0.0.0.0:8517
数据库复用 warehouse_app/records.db
依赖: flask, sqlite3 (内置)
"""

import os
import sys
import sqlite3
import hashlib
import csv
import io
from datetime import datetime, date

from flask import (
    Flask, request, session, redirect, url_for,
    render_template_string, jsonify, flash, make_response
)

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "warehouse_secret_key_2024"

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "records.db")

# ─────────────────────────────────────────────
# 数据库工具
# ─────────────────────────────────────────────
def _hash(pw):
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS inventory (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT    UNIQUE NOT NULL,
        quantity  INTEGER NOT NULL DEFAULT 0,
        warn_qty  INTEGER NOT NULL DEFAULT 5
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS records (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        type        TEXT    NOT NULL,
        item_name   TEXT    NOT NULL,
        quantity    INTEGER NOT NULL,
        operator    TEXT    NOT NULL,
        record_date TEXT    NOT NULL,
        record_time TEXT    DEFAULT '',
        remark      TEXT    DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS oplog (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        action     TEXT    NOT NULL,
        detail     TEXT    NOT NULL,
        oplog_date TEXT    NOT NULL,
        oplog_time TEXT    NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT    UNIQUE NOT NULL,
        password TEXT    NOT NULL,
        role     TEXT    NOT NULL DEFAULT 'user'
    )""")
    for col, coltype in [("remark", "TEXT DEFAULT ''"), ("record_time", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE records ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("ALTER TABLE inventory ADD COLUMN warn_qty INTEGER NOT NULL DEFAULT 5")
    except sqlite3.OperationalError:
        pass
    c.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                  ("admin", _hash("admin123"), "admin"))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# 权限检查
# ─────────────────────────────────────────────
def login_db(username, password):
    conn = get_db()
    row = conn.execute("SELECT role FROM users WHERE username=? AND password=?",
                       (username, _hash(password))).fetchone()
    conn.close()
    return row["role"] if row else None

def is_admin():
    return session.get("role") == "admin"

# ─────────────────────────────────────────────
# HTML 模板（完整页面，不依赖 extends）
# ─────────────────────────────────────────────

NAV_HTML = """
<div class="header">
  <h1>📦 出入库管理系统 v1.0（Web版）</h1>
  <div class="user-info">
    👤 {{ session.user }}
    {% if session.role == 'admin' %}
      <span style="background:#DC2626;color:white;padding:2px 8px;border-radius:10px;font-size:12px;">管理员</span>
    {% else %}
      <span style="background:#6B7280;color:white;padding:2px 8px;border-radius:10px;font-size:12px;">普通用户</span>
    {% endif %}
    | <a href="/change_password">修改密码</a>
    | <a href="/logout">退出</a>
  </div>
</div>
<div class="nav">
  <a href="/"         {% if active=='home'     %}class="active"{% endif %}>🏠 首页</a>
  <a href="/records"  {% if active=='records'  %}class="active"{% endif %}>📋 出入库记录</a>
  <a href="/inventory"{% if active=='inventory'%}class="active"{% endif %}>📦 库存台账</a>
  <a href="/warnings" {% if active=='warnings' %}class="active"{% endif %}>⚠️ 低库存</a>
  <a href="/oplog"    {% if active=='oplog'    %}class="active"{% endif %}>📜 操作日志</a>
  {% if session.role == 'admin' %}
  <a href="/users"    {% if active=='users'    %}class="active"{% endif %}>👥 账号管理</a>
  {% endif %}
</div>
"""

BASE_LAYOUT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title|default('出入库管理系统') }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:"Microsoft YaHei","微软雅黑",Arial,sans-serif;background:#F5F6FA;color:#1A1D2E;font-size:14px;}
.header{background:#3A57E8;color:white;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;}
.header h1{font-size:18px;font-weight:bold;}
.header a{color:#FFD700;text-decoration:none;margin-left:10px;font-size:13px;}
.nav{background:white;padding:0 24px;display:flex;gap:0;border-bottom:1px solid #E0E3EF;}
.nav a{display:inline-block;padding:10px 16px;text-decoration:none;color:#6B7280;font-size:14px;border-bottom:2px solid transparent;}
.nav a:hover,.nav a.active{color:#3A57E8;border-bottom-color:#3A57E8;}
.container{max-width:1200px;margin:20px auto;padding:0 16px;}
.card{background:white;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);}
.card h2{font-size:16px;margin-bottom:16px;color:#1A1D2E;}
.form-row{display:flex;gap:12px;margin-bottom:12px;align-items:center;flex-wrap:wrap;}
.form-row label{min-width:65px;color:#6B7280;font-size:14px;}
.form-row input,.form-row select{padding:6px 10px;border:1px solid #E0E3EF;border-radius:4px;font-size:14px;outline:none;}
.form-row input:focus,.form-row select:focus{border-color:#3A57E8;}
.btn{padding:7px 16px;border:none;border-radius:4px;font-size:14px;cursor:pointer;display:inline-block;text-decoration:none;}
.btn-primary{background:#3A57E8;color:white;}
.btn-success{background:#22A06B;color:white;}
.btn-danger{background:#E84B4B;color:white;}
.btn-warning{background:#F59E0B;color:white;}
.btn-info{background:#7C3AED;color:white;}
.btn-sm{padding:4px 10px;font-size:12px;}
.btn:hover{opacity:0.85;}
.flash{padding:10px 16px;border-radius:4px;margin-bottom:16px;font-size:14px;}
.flash.success{background:#EEF9F2;color:#1A7A4A;border:1px solid #22A06B;}
.flash.danger{background:#FFF0F0;color:#C0392B;border:1px solid #E84B4B;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{background:#F5F6FA;padding:8px 10px;text-align:center;font-weight:bold;border-bottom:2px solid #E0E3EF;}
td{padding:7px 10px;text-align:center;border-bottom:1px solid #F0F0F0;}
tr:hover{background:#F9FAFF;}
.type-in{color:#1A7A4A;font-weight:bold;}
.type-out{color:#C0392B;font-weight:bold;}
.type-ret{color:#B45309;font-weight:bold;}
.low-stock{color:#EF4444;font-weight:bold;}
.stats{display:flex;gap:20px;margin-bottom:16px;}
.stat-box{background:white;padding:12px 20px;border-radius:6px;min-width:120px;text-align:center;}
.stat-box .num{font-size:24px;font-weight:bold;}
.stat-box .label{font-size:12px;color:#6B7280;}
.filter-bar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;}
.filter-bar input,.filter-bar select{padding:5px 8px;border:1px solid #E0E3EF;border-radius:4px;font-size:13px;}
.login-box{max-width:380px;margin:100px auto;background:white;padding:32px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,0.1);}
.login-box h1{text-align:center;color:#3A57E8;margin-bottom:24px;}
.login-box input{width:100%;padding:10px;margin-bottom:14px;border:1px solid #E0E3EF;border-radius:4px;font-size:15px;}
.login-box button{width:100%;padding:10px;background:#3A57E8;color:white;border:none;border-radius:4px;font-size:16px;cursor:pointer;}
</style>
</head>
<body>
{% if session.user %}
{{ nav|safe }}
{% endif %}
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="flash {{ cat }}">{{ msg }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {{ content|safe }}
</div>
</body>
</html>
"""

def render_page(content, title="出入库管理系统", active=""):
    """渲染完整页面"""
    nav = render_template_string(NAV_HTML, active=active, session=session)
    full_content = render_template_string(
        BASE_LAYOUT,
        title=title,
        nav=nav,
        content=content,
        session=session
    )
    return full_content

# ─────────────────────────────────────────────
# 各页面内容模板
# ─────────────────────────────────────────────

LOGIN_CONTENT = """
<div class="login-box">
  <h1>📦 出入库管理系统</h1>
  <form method="post">
    <input name="username" placeholder="用户名" required autofocus>
    <input name="password" type="password" placeholder="密码" required>
    <button type="submit">登  录</button>
  </form>

</div>
"""

INDEX_CONTENT = """
<div class="stats">
  <div class="stat-box"><div class="num" style="color:#22A06B;">{{ stats.in }}</div><div class="label">今日入库</div></div>
  <div class="stat-box"><div class="num" style="color:#E84B4B;">{{ stats.out }}</div><div class="label">今日出货</div></div>
  <div class="stat-box"><div class="num" style="color:#F59E0B;">{{ stats.ret }}</div><div class="label">今日退货</div></div>
  <div class="stat-box"><div class="num" style="color:#3A57E8;">{{ inv_stats.total_kinds }}</div><div class="label">物品种类</div></div>
  <div class="stat-box"><div class="num" style="color:#DC2626;">{{ inv_stats.warn_count }}</div><div class="label">低库存预警</div></div>
</div>

<div class="card">
  <h2>📦 当前库存概览</h2>
  {% if inventory %}
  <table>
    <tr><th>物品名称</th><th>库存数量</th><th>预警值</th><th>状态</th></tr>
    {% for r in inventory %}
    <tr>
      <td style="text-align:left;padding-left:12px;">{{ r.item_name }}</td>
      <td {% if r.quantity <= r.warn_qty %}class="low-stock"{% endif %}>{{ r.quantity }} 件</td>
      <td>{{ r.warn_qty }} 件</td>
      <td>{% if r.quantity==0 %}🈳 缺货{% elif r.quantity<=r.warn_qty %}⚠️ 预警{% else %}✅ 充足{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p style="color:#999;padding:12px;">暂无库存数据，请先进行入库操作。</p>
  {% endif %}
</div>

<div class="card">
  <h2>📝 新增出入库记录</h2>
  <form method="post" action="/submit">
    <div class="form-row">
      <label>操作类型</label>
      <select name="type">
        <option value="入库">📥 入库</option>
        <option value="出货">📤 出货</option>
        <option value="退货">↩️ 退货</option>
      </select>
    </div>
    <div class="form-row">
      <label>物品名称</label>
      <input name="item_name" list="item-list" required style="width:220px;">
      <datalist id="item-list">{% for item in items %}<option value="{{ item }}">{% endfor %}</datalist>
    </div>
    <div class="form-row">
      <label>数　量</label>
      <input name="quantity" type="number" min="1" value="1" required style="width:120px;">
    </div>
    <div class="form-row">
      <label>操作人员</label>
      <input name="operator" value="{{ session.user }}" required style="width:160px;">
    </div>
    <div class="form-row">
      <label>备　注</label>
      <input name="remark" style="width:260px;" placeholder="可选">
    </div>
    <div class="form-row"><button type="submit" class="btn btn-success">✔ 提交记录</button></div>
  </form>
</div>

<div class="card">
  <h2>今日出入库明细</h2>
  <table>
    <tr><th>ID</th><th>类型</th><th>物品名称</th><th>数量</th><th>操作人</th><th>时间</th><th>备注</th>
    {% if session.role == 'admin' %}<th>操作</th>{% endif %}</tr>
    {% for r in today_records %}
    <tr>
      <td>{{ r.id }}</td>
      <td class="type-{{ {'入库':'in','出货':'out','退货':'ret'}.get(r.type,'') }}">{{ r.type }}</td>
      <td style="text-align:left;padding-left:12px;">{{ r.item_name }}</td>
      <td>{{ r.quantity }}</td>
      <td>{{ r.operator }}</td>
      <td>{{ r.record_time or '' }}</td>
      <td style="text-align:left;">{{ r.remark or '' }}</td>
      {% if session.role == 'admin' %}
      <td>
        <a href="/edit_record/{{ r.id }}" class="btn btn-info btn-sm">编辑</a>
        <a href="/delete_record/{{ r.id }}" class="btn btn-danger btn-sm" onclick="return confirm('确定删除？库存将回滚！')">删除</a>
      </td>
      {% endif %}
    </tr>
    {% else %}
    <tr><td colspan="8" style="color:#999;">暂无今日记录</td></tr>
    {% endfor %}
  </table>
</div>
"""

RECORDS_CONTENT = """
<div class="card">
  <h2>📋 出入库记录查询</h2>
  <form method="get" action="/records" class="filter-bar">
    <label>起始 <input name="start" type="date" value="{{ start }}"></label>
    <label>结束 <input name="end" type="date" value="{{ end }}"></label>
    <label>类型
      <select name="type">
        <option value="">全部</option>
        <option value="入库" {% if ftype=='入库' %}selected{% endif %}>入库</option>
        <option value="出货" {% if ftype=='出货' %}selected{% endif %}>出货</option>
        <option value="退货" {% if ftype=='退货' %}selected{% endif %}>退货</option>
      </select>
    </label>
    <label>物品 <input name="item_kw" value="{{ item_kw }}" placeholder="关键词" style="width:100px;"></label>
    <button class="btn btn-primary btn-sm">查询</button>
    <a href="/records" class="btn btn-sm" style="background:#E0E3EF;">重置</a>
    <a href="/export?start={{ start }}&end={{ end }}&type={{ ftype }}&item_kw={{ item_kw }}" class="btn btn-success btn-sm">📤 导出CSV</a>
  </form>
  <table>
    <tr><th>ID</th><th>类型</th><th>物品名称</th><th>数量</th><th>操作人</th><th>日期</th><th>时间</th><th>备注</th>
    {% if session.role == 'admin' %}<th>操作</th>{% endif %}</tr>
    {% for r in records %}
    <tr>
      <td>{{ r.id }}</td>
      <td class="type-{{ {'入库':'in','出货':'out','退货':'ret'}.get(r.type,'') }}">{{ r.type }}</td>
      <td style="text-align:left;padding-left:12px;">{{ r.item_name }}</td>
      <td>{{ r.quantity }}</td>
      <td>{{ r.operator }}</td>
      <td>{{ r.record_date }}</td>
      <td>{{ r.record_time or '' }}</td>
      <td style="text-align:left;">{{ r.remark or '' }}</td>
      {% if session.role == 'admin' %}
      <td>
        <a href="/edit_record/{{ r.id }}" class="btn btn-info btn-sm">编辑</a>
        <a href="/delete_record/{{ r.id }}" class="btn btn-danger btn-sm" onclick="return confirm('确定删除？')">删除</a>
      </td>
      {% endif %}
    </tr>
    {% else %}
    <tr><td colspan="9" style="color:#999;">暂无记录</td></tr>
    {% endfor %}
  </table>
  <p style="margin-top:10px;color:#6B7280;font-size:13px;">共 {{ records|length }} 条</p>
</div>
"""

INVENTORY_CONTENT = """
<div class="card">
  <h2>📦 库存台账</h2>
  <table>
    <tr><th>物品名称</th><th>库存</th><th>预警值</th><th>状态</th>{% if session.role=='admin' %}<th>操作</th>{% endif %}</tr>
    {% for r in inventory %}
    <tr>
      <td style="text-align:left;padding-left:12px;">{{ r.item_name }}</td>
      <td {% if r.quantity <= r.warn_qty %}class="low-stock"{% endif %}>{{ r.quantity }} 件</td>
      <td>{{ r.warn_qty }} 件</td>
      <td>{% if r.quantity==0 %}🈳 缺货{% elif r.quantity<=r.warn_qty %}⚠️ 预警{% else %}✅ 充足{% endif %}</td>
      {% if session.role == 'admin' %}
      <td><a href="/edit_inventory?item={{ r.item_name|urlencode }}" class="btn btn-warning btn-sm">修改</a></td>
      {% endif %}
    </tr>
    {% else %}
    <tr><td colspan="5" style="color:#999;">暂无数据</td></tr>
    {% endfor %}
  </table>
</div>

<div class="card">
  <h2>⚙️ 预警阈值设置</h2>
  <form method="post" action="/set_warn" class="filter-bar">
    <label>物品 <input name="item_name" list="ilist" required style="width:160px;"></label>
    <datalist id="ilist">{% for r in inventory %}<option value="{{ r.item_name }}">{% endfor %}</datalist>
    <label>阈值 <input name="warn_qty" type="number" min="0" value="5" style="width:80px;" required></label>
    <button class="btn btn-warning btn-sm">设置</button>
  </form>
</div>
"""

WARNINGS_CONTENT = """
<div class="card">
  <h2>⚠️ 低库存预警</h2>
  {% if items %}
  <table>
    <tr><th>物品名称</th><th>当前库存</th><th>预警值</th><th>缺口</th></tr>
    {% for name,qty,warn in items %}
    <tr>
      <td style="text-align:left;padding-left:12px;">{{ name }}</td>
      <td class="low-stock">{{ qty }} 件</td>
      <td>{{ warn }} 件</td>
      <td class="low-stock">{{ warn - qty }} 件</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p style="color:#22A06B;font-size:15px;padding:20px;">✅ 暂无预警，所有物品库存充足。</p>
  {% endif %}
</div>
"""

OPLOG_CONTENT = """
<div class="card">
  <h2>📜 操作日志（最近50条）</h2>
  <table>
    <tr><th>日期</th><th>时间</th><th>操作</th><th>详情</th></tr>
    {% for r in logs %}
    <tr>
      <td>{{ r.oplog_date }}</td>
      <td>{{ r.oplog_time }}</td>
      <td class="type-{{ {'入库':'in','出货':'out','退货':'ret'}.get(r.action,'') }}">{{ r.action }}</td>
      <td style="text-align:left;padding-left:12px;">{{ r.detail }}</td>
    </tr>
    {% else %}
    <tr><td colspan="4" style="color:#999;">暂无日志</td></tr>
    {% endfor %}
  </table>
</div>
"""

USERS_CONTENT = """
<div class="card">
  <h2>👥 账号管理</h2>
  <p style="color:#6B7280;font-size:13px;margin-bottom:12px;">
    管理员：全部权限 | 普通用户：仅出入库
  </p>
  <form method="post" action="/add_user" class="filter-bar">
    <label>用户名 <input name="username" required style="width:110px;"></label>
    <label>密码 <input name="password" type="password" required style="width:110px;"></label>
    <label>角色
      <select name="role"><option value="user">普通用户</option><option value="admin">管理员</option></select>
    </label>
    <button class="btn btn-success btn-sm">➕ 新增</button>
  </form>
  <table style="margin-top:16px;">
    <tr><th>ID</th><th>用户名</th><th>角色</th><th>操作</th></tr>
    {% for u in users %}
    <tr>
      <td>{{ u.id }}</td>
      <td>{{ u.username }}</td>
      <td>{% if u.role=='admin' %}<span style="background:#DC2626;color:white;padding:2px 8px;border-radius:10px;font-size:12px;">管理员</span>
          {% else %}<span style="background:#6B7280;color:white;padding:2px 8px;border-radius:10px;font-size:12px;">普通用户</span>{% endif %}</td>
      <td>
        {% if u.username != 'admin' and u.username != session.user %}
        <a href="/toggle_role?uid={{ u.id }}" class="btn btn-warning btn-sm" onclick="return confirm('切换角色？')">切换</a>
        <a href="/delete_user?uid={{ u.id }}" class="btn btn-danger btn-sm" onclick="return confirm('删除用户？')">删除</a>
        {% endif %}
        <a href="/reset_password?uid={{ u.id }}" class="btn btn-info btn-sm">重置密码</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
"""

EDIT_RECORD_CONTENT = """
<div class="card" style="max-width:500px;">
  <h2>✏️ 编辑记录 ID={{ r.id }}</h2>
  <form method="post" action="/edit_record/{{ r.id }}">
    <div class="form-row"><label>物品</label><input name="item_name" value="{{ r.item_name }}" required></div>
    <div class="form-row"><label>数量</label><input name="quantity" type="number" min="1" value="{{ r.quantity }}" required></div>
    <div class="form-row"><label>操作人</label><input name="operator" value="{{ r.operator }}" required></div>
    <div class="form-row"><label>备注</label><input name="remark" value="{{ r.remark or '' }}"></div>
    <p style="color:#E84B4B;font-size:13px;">⚠️ 修改将自动回滚旧库存并应用新库存</p>
    <div class="form-row"><button class="btn btn-primary">保存</button> <a href="/records" style="margin-left:8px;">取消</a></div>
  </form>
</div>
"""

CHANGE_PW_CONTENT = """
<div class="card" style="max-width:420px;">
  <h2>🔑 修改密码</h2>
  <form method="post">
    <div class="form-row"><label>当前密码</label><input name="old_pw" type="password" required></div>
    <div class="form-row"><label>新密码</label><input name="new_pw" type="password" required minlength="4"></div>
    <div class="form-row"><label>确认密码</label><input name="cfm_pw" type="password" required minlength="4"></div>
    <div class="form-row"><button class="btn btn-primary">确认修改</button></div>
  </form>
</div>
"""

RESET_PW_CONTENT = """
<div class="card" style="max-width:420px;">
  <h2>🔑 重置密码 - {{ username }}</h2>
  <form method="post">
    <div class="form-row"><label>新密码</label><input name="new_pw" type="password" required minlength="4"></div>
    <div class="form-row"><label>确认密码</label><input name="cfm_pw" type="password" required minlength="4"></div>
    <div class="form-row"><button class="btn btn-primary">确认重置</button></div>
  </form>
</div>
"""

EDIT_INV_CONTENT = """
<div class="card" style="max-width:420px;">
  <h2>✏️ 修改库存 - {{ item }}</h2>
  <form method="post">
    <div class="form-row"><label>当前库存</label><input disabled value="{{ cur_qty }} 件" style="background:#F5F6FA;"></div>
    <div class="form-row"><label>新库存</label><input name="new_qty" type="number" min="0" value="{{ cur_qty }}" required></div>
    <div class="form-row"><button class="btn btn-warning">保存</button></div>
  </form>
</div>
"""

# ─────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = login_db(username, password)
        if role:
            session["user"] = username
            session["role"] = role
            return redirect("/")
        flash("用户名或密码错误！", "danger")
    return render_page(LOGIN_CONTENT, title="登录", active="")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

def login_required():
    if "user" not in session:
        return redirect("/login")

@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")
    today = date.today().strftime("%Y-%m-%d")
    conn = get_db()
    stats_row = conn.execute(
        "SELECT type, SUM(quantity) FROM records WHERE record_date=? GROUP BY type", (today,)
    ).fetchall()
    stats = {"in": 0, "out": 0, "ret": 0}
    for r in stats_row:
        if r[0] == "入库": stats["in"] = r[1] or 0
        elif r[0] == "出货": stats["out"] = r[1] or 0
        elif r[0] == "退货": stats["ret"] = r[1] or 0
    today_records = conn.execute(
        "SELECT id,type,item_name,quantity,operator,record_date,record_time,remark "
        "FROM records WHERE record_date=? ORDER BY id DESC", (today,)
    ).fetchall()
    items = [r["item_name"] for r in conn.execute("SELECT DISTINCT item_name FROM inventory ORDER BY item_name").fetchall()]
    inventory = conn.execute("SELECT item_name,quantity,warn_qty FROM inventory ORDER BY item_name").fetchall()
    inv_warn = conn.execute("SELECT COUNT(*) FROM inventory WHERE quantity <= warn_qty").fetchone()[0]
    inv_stats = {"total_kinds": len(inventory), "warn_count": inv_warn}
    conn.close()
    content = render_template_string(INDEX_CONTENT, stats=stats, today_records=today_records, items=items, inventory=inventory, inv_stats=inv_stats)
    return render_page(content, active="home")

@app.route("/submit", methods=["POST"])
def submit_record():
    if "user" not in session:
        return redirect("/login")
    rec_type  = request.form.get("type", "入库")
    item_name = request.form.get("item_name", "").strip()
    operator  = request.form.get("operator", session["user"]).strip()
    remark    = request.form.get("remark", "").strip()
    try:
        quantity = int(request.form.get("quantity", "1"))
        assert quantity > 0
    except:
        flash("数量必须是正整数！", "danger")
        return redirect("/")
    if not item_name:
        flash("请填写物品名称！", "danger")
        return redirect("/")
    now = datetime.now()
    dt, tm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    conn = get_db()
    c = conn.cursor()
    if rec_type == "入库":
        c.execute("INSERT INTO inventory (item_name,quantity,warn_qty) VALUES (?,?,5) "
                  "ON CONFLICT(item_name) DO UPDATE SET quantity=quantity+?", (item_name, quantity, quantity))
    else:
        delta = -quantity if rec_type == "出货" else quantity
        row = c.execute("SELECT quantity FROM inventory WHERE item_name=?", (item_name,)).fetchone()
        if row is None and rec_type != "退货":
            flash("库存不足或物品不存在！", "danger")
            conn.close()
            return redirect("/")
        elif row is None:
            c.execute("INSERT INTO inventory (item_name,quantity,warn_qty) VALUES (?,?,5)", (item_name, quantity))
        elif row[0] + delta < 0:
            flash("库存不足，无法操作！", "danger")
            conn.close()
            return redirect("/")
        else:
            c.execute("UPDATE inventory SET quantity=quantity+? WHERE item_name=?", (delta, item_name))
    c.execute("INSERT INTO records (type,item_name,quantity,operator,record_date,record_time,remark) VALUES (?,?,?,?,?,?,?)",
              (rec_type, item_name, quantity, operator, dt, tm, remark))
    c.execute("INSERT INTO oplog (action,detail,oplog_date,oplog_time) VALUES (?,?,?,?)",
              (rec_type, f"「{item_name}」{rec_type}数量{quantity}，操作人：{operator}", dt, tm))
    conn.commit()
    conn.close()
    flash(f"✅ {rec_type}成功！{item_name} {quantity}件", "success")
    return redirect("/")

@app.route("/records")
def records():
    if "user" not in session:
        return redirect("/login")
    start   = request.args.get("start", date.today().strftime("%Y-%m-%d"))
    end     = request.args.get("end",   date.today().strftime("%Y-%m-%d"))
    ftype   = request.args.get("type", "")
    item_kw = request.args.get("item_kw", "")
    sql = "SELECT id,type,item_name,quantity,operator,record_date,record_time,remark FROM records WHERE 1=1"
    params = []
    if start and end:
        sql += " AND record_date BETWEEN ? AND ?"
        params += [start, end]
    if ftype:
        sql += " AND type=?"
        params.append(ftype)
    if item_kw:
        sql += " AND item_name LIKE ?"
        params.append(f"%{item_kw}%")
    sql += " ORDER BY id DESC"
    conn = get_db()
    records = conn.execute(sql, params).fetchall()
    conn.close()
    content = render_template_string(RECORDS_CONTENT, records=records, start=start, end=end, ftype=ftype, item_kw=item_kw)
    return render_page(content, active="records")

@app.route("/inventory")
def inventory():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    inventory = conn.execute("SELECT item_name,quantity,warn_qty FROM inventory ORDER BY item_name").fetchall()
    conn.close()
    content = render_template_string(INVENTORY_CONTENT, inventory=inventory)
    return render_page(content, active="inventory")

@app.route("/warnings")
def warnings():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    items = conn.execute("SELECT item_name,quantity,warn_qty FROM inventory WHERE quantity <= warn_qty ORDER BY quantity ASC").fetchall()
    conn.close()
    content = render_template_string(WARNINGS_CONTENT, items=items)
    return render_page(content, active="warnings")

@app.route("/oplog")
def oplog():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    logs = conn.execute("SELECT action,detail,oplog_date,oplog_time FROM oplog ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    content = render_template_string(OPLOG_CONTENT, logs=logs)
    return render_page(content, active="oplog")

@app.route("/edit_record/<int:rid>", methods=["GET", "POST"])
def edit_record(rid):
    if "user" not in session or session["role"] != "admin":
        flash("需要管理员权限！", "danger")
        return redirect("/records")
    conn = get_db()
    if request.method == "POST":
        new_item = request.form.get("item_name", "").strip()
        new_qty  = int(request.form.get("quantity", 1))
        new_op   = request.form.get("operator", "").strip()
        new_rem  = request.form.get("remark", "").strip()
        old = conn.execute("SELECT type,item_name,quantity FROM records WHERE id=?", (rid,)).fetchone()
        if old:
            old_type, old_item, old_qty = old["type"], old["item_name"], old["quantity"]
            old_delta = -old_qty if old_type == "入库" else (old_qty if old_type == "出货" else -old_qty)
            conn.execute("UPDATE inventory SET quantity=quantity+? WHERE item_name=?", (old_delta, old_item))
            new_delta = new_qty if old_type == "入库" else (-new_qty if old_type == "出货" else new_qty)
            conn.execute("INSERT INTO inventory (item_name,quantity,warn_qty) VALUES (?,?,5) "
                        "ON CONFLICT(item_name) DO UPDATE SET quantity=quantity+?", (new_item, new_delta, new_delta))
            conn.execute("UPDATE records SET item_name=?,quantity=?,operator=?,remark=? WHERE id=?",
                         (new_item, new_qty, new_op, new_rem, rid))
            now = datetime.now()
            conn.execute("INSERT INTO oplog (action,detail,oplog_date,oplog_time) VALUES (?,?,?,?)",
                         ("修改", f"修改记录ID{rid}：「{old_item}」→「{new_item}」数量{old_qty}→{new_qty}",
                          now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")))
            conn.commit()
            flash("✅ 记录已更新！", "success")
        conn.close()
        return redirect("/records")
    r = conn.execute("SELECT id,type,item_name,quantity,operator,remark FROM records WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not r:
        flash("记录不存在！", "danger")
        return redirect("/records")
    content = render_template_string(EDIT_RECORD_CONTENT, r=r)
    return render_page(content, active="records")

@app.route("/delete_record/<int:rid>")
def delete_record(rid):
    if "user" not in session or session["role"] != "admin":
        flash("需要管理员权限！", "danger")
        return redirect("/records")
    conn = get_db()
    row = conn.execute("SELECT type,item_name,quantity FROM records WHERE id=?", (rid,)).fetchone()
    if row:
        rec_type, item_name, quantity = row["type"], row["item_name"], row["quantity"]
        delta = -quantity if rec_type == "入库" else (quantity if rec_type == "出货" else -quantity)
        conn.execute("UPDATE inventory SET quantity=quantity+? WHERE item_name=?", (delta, item_name))
        conn.execute("DELETE FROM records WHERE id=?", (rid,))
        now = datetime.now()
        conn.execute("INSERT INTO oplog (action,detail,oplog_date,oplog_time) VALUES (?,?,?,?)",
                     ("删除", f"删除「{item_name}」{quantity}件（{rec_type}）", now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")))
        conn.commit()
        flash("✅ 已删除，库存已回滚", "success")
    conn.close()
    return redirect(request.referrer or "/records")

@app.route("/edit_inventory", methods=["GET", "POST"])
def edit_inventory():
    if "user" not in session or session["role"] != "admin":
        flash("需要管理员权限！", "danger")
        return redirect("/inventory")
    item = request.args.get("item") or request.form.get("item_name", "")
    conn = get_db()
    cur = conn.execute("SELECT quantity FROM inventory WHERE item_name=?", (item,)).fetchone()
    if not cur:
        flash("物品不存在！", "danger")
        return redirect("/inventory")
    cur_qty = cur["quantity"]
    if request.method == "POST":
        new_qty = int(request.form.get("new_qty", cur_qty))
        conn.execute("UPDATE inventory SET quantity=? WHERE item_name=?", (new_qty, item))
        now = datetime.now()
        conn.execute("INSERT INTO oplog (action,detail,oplog_date,oplog_time) VALUES (?,?,?,?)",
                     ("修改库存", f"「{item}」库存：{cur_qty}→{new_qty}件", now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")))
        conn.commit()
        flash(f"✅ 库存已更新为 {new_qty} 件", "success")
        conn.close()
        return redirect("/inventory")
    conn.close()
    content = render_template_string(EDIT_INV_CONTENT, item=item, cur_qty=cur_qty)
    return render_page(content, active="inventory")

@app.route("/set_warn", methods=["POST"])
def set_warn():
    if "user" not in session:
        return redirect("/login")
    item_name = request.form.get("item_name", "").strip()
    try:
        warn_qty = int(request.form.get("warn_qty", 5))
    except:
        warn_qty = 5
    if item_name:
        conn = get_db()
        conn.execute("UPDATE inventory SET warn_qty=? WHERE item_name LIKE ?", (warn_qty, f"%{item_name}%"))
        conn.commit()
        conn.close()
        flash(f"✅ 「{item_name}」预警阈值设为 {warn_qty}", "success")
    return redirect("/inventory")

@app.route("/export")
def export_csv():
    if "user" not in session:
        return redirect("/login")
    try:
        start   = request.args.get("start", "")
        end     = request.args.get("end", "")
        ftype   = request.args.get("type", "")
        item_kw = request.args.get("item_kw", "")
        sql = "SELECT record_date,record_time,type,item_name,quantity,operator,remark FROM records WHERE 1=1"
        params = []
        if start and end:
            sql += " AND record_date BETWEEN ? AND ?"
            params += [start, end]
        if ftype:
            sql += " AND type=?"
            params.append(ftype)
        if item_kw:
            sql += " AND item_name LIKE ?"
            params.append(f"%{item_kw}%")
        sql += " ORDER BY id DESC"
        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        output = io.StringIO()
        output.write('\ufeff')  # BOM头，让Excel正确识别UTF-8中文
        writer = csv.writer(output)
        writer.writerow(["日期","时间","类型","物品名称","数量","操作人","备注"])
        for r in rows:
            writer.writerow([r["record_date"], r["record_time"], r["type"], r["item_name"], r["quantity"], r["operator"], r["remark"] or ""])
        from urllib.parse import quote
        filename = f"warehouse_records_{start}_{end}.csv"
        resp = make_response(output.getvalue().encode('utf-8'))
        resp.headers["Content-Disposition"] = f"attachment; filename={filename}; filename*=UTF-8''{quote('出入库记录_' + start + '_至_' + end + '.csv')}"
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        return resp
    except Exception as e:
        flash(f"导出失败：{e}", "danger")
        return redirect("/records")

@app.route("/users")
def user_manage():
    if "user" not in session or session["role"] != "admin":
        flash("需要管理员权限！", "danger")
        return redirect("/")
    conn = get_db()
    users = conn.execute("SELECT id,username,role FROM users ORDER BY id").fetchall()
    conn.close()
    content = render_template_string(USERS_CONTENT, users=users)
    return render_page(content, active="users")

@app.route("/add_user", methods=["POST"])
def add_user():
    if "user" not in session or session["role"] != "admin":
        return redirect("/login")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role     = request.form.get("role", "user")
    if not username or not password:
        flash("用户名和密码不能为空！", "danger")
        return redirect("/users")
    try:
        conn = get_db()
        conn.execute("INSERT INTO users (username,password,role) VALUES (?,?,?)", (username, _hash(password), role))
        conn.commit()
        conn.close()
        flash(f"✅ 用户「{username}」已添加！", "success")
    except Exception as e:
        flash(f"添加失败：{e}", "danger")
    return redirect("/users")

@app.route("/toggle_role")
def toggle_role():
    if "user" not in session or session["role"] != "admin":
        return redirect("/login")
    uid = request.args.get("uid", type=int)
    conn = get_db()
    u = conn.execute("SELECT username,role FROM users WHERE id=?", (uid,)).fetchone()
    if u and u["username"] != "admin":
        new_role = "user" if u["role"] == "admin" else "admin"
        conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, uid))
        conn.commit()
        flash(f"✅ 已切换为{'管理员' if new_role=='admin' else '普通用户'}", "success")
    conn.close()
    return redirect("/users")

@app.route("/delete_user")
def delete_user():
    if "user" not in session or session["role"] != "admin":
        return redirect("/login")
    uid = request.args.get("uid", type=int)
    conn = get_db()
    u = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if u and u["username"] != "admin" and u["username"] != session["user"]:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        flash(f"✅ 用户「{u['username']}」已删除", "success")
    conn.close()
    return redirect("/users")

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if "user" not in session or session["role"] != "admin":
        return redirect("/login")
    uid = request.args.get("uid", type=int)
    conn = get_db()
    u = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        flash("用户不存在！", "danger")
        return redirect("/users")
    if request.method == "POST":
        new_pw = request.form.get("new_pw", "")
        cfm_pw = request.form.get("cfm_pw", "")
        if len(new_pw) < 4:
            flash("密码至少4位！", "danger")
            conn.close()
            return redirect(f"/reset_password?uid={uid}")
        if new_pw != cfm_pw:
            flash("两次密码不一致！", "danger")
            conn.close()
            return redirect(f"/reset_password?uid={uid}")
        conn.execute("UPDATE users SET password=? WHERE id=?", (_hash(new_pw), uid))
        conn.commit()
        flash(f"✅ 「{u['username']}」密码已重置", "success")
        conn.close()
        return redirect("/users")
    conn.close()
    content = render_template_string(RESET_PW_CONTENT, username=u["username"])
    return render_page(content, active="users")

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "user" not in session:
        return redirect("/login")
    if request.method == "POST":
        old_pw = request.form.get("old_pw", "")
        new_pw = request.form.get("new_pw", "")
        cfm_pw = request.form.get("cfm_pw", "")
        conn = get_db()
        u = conn.execute("SELECT password FROM users WHERE username=?", (session["user"],)).fetchone()
        if not u or u["password"] != _hash(old_pw):
            flash("当前密码不正确！", "danger")
            conn.close()
            return redirect("/change_password")
        if len(new_pw) < 4:
            flash("新密码至少4位！", "danger")
            conn.close()
            return redirect("/change_password")
        if new_pw != cfm_pw:
            flash("两次密码不一致！", "danger")
            conn.close()
            return redirect("/change_password")
        conn.execute("UPDATE users SET password=? WHERE username=?", (_hash(new_pw), session["user"]))
        conn.commit()
        conn.close()
        flash("✅ 密码已修改，下次登录生效！", "success")
        return redirect("/")
    content = render_template_string(CHANGE_PW_CONTENT)
    return render_page(content, active="home")

# ─────────────────────────────────────────────
# 启动
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  出入库管理系统 Web 版")
    print("  访问: http://0.0.0.0:8517")
    print("  默认: admin / admin123")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8517, debug=False, threaded=True)
