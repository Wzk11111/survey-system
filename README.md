# 基于 MongoDB 的问卷系统（大作业一 · 第一阶段）

一个简化版在线问卷系统，功能类似“问卷星/Google Forms”，数据全部存储在 MongoDB。
支持用户注册登录、问卷创建与管理、三种题型（单选/多选/文本填空/数字填空）、题目跳转、填写校验与统计结果。

## 技术栈

- 后端：Python 3.9 + Flask 3.1 + PyMongo 4.18
- 数据库：MongoDB 6.0（本地 127.0.0.1:27017）
- 前端：原生 HTML + 少量 JavaScript（无构建步骤）

## 目录结构

```
大作业一_问卷系统/
├── app.py              # Flask 后端：API + 跳转/校验/统计引擎
├── static/
│   ├── index.html      # 登录/注册
│   ├── dashboard.html  # 我的问卷列表/创建
│   ├── editor.html     # 问卷编辑（题目/选项/校验/跳转）
│   ├── fill.html       # 填写页（自动跳转 + 实时校验）
│   ├── stats.html      # 统计结果页
│   ├── css/style.css
│   └── js/common.js
├── tests/              # pytest 自动化测试（独立测试库 survey_test）
│   ├── conftest.py
│   ├── helpers.py
│   ├── test_api.py     # 11 个 API 集成测试
│   └── test_engines.py # 9 个跳转/校验单元测试
├── pytest.ini
├── requirements.txt
└── run.bat             # 一键启动服务
```

## 快速启动

1. 启动 MongoDB（本机 27017 端口）。可使用 `D:\大三\数据管理系统\启动MongoDB.bat`，或：
   ```
   "D:\MongoDB\Server\6.0\bin\mongod.exe" --dbpath "D:\MongoDB\data" --port 27017 --bind_ip 127.0.0.1
   ```
2. 安装依赖：
   ```
   pip install -r requirements.txt
   ```
3. 启动服务：
   ```
   python app.py        # 或双击 run.bat
   ```
4. 浏览器打开 http://127.0.0.1:5000

## 运行测试

```
python -m pytest -c pytest.ini
```

测试使用独立数据库 `survey_test`，不会影响正式数据。

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| MONGO_URI | mongodb://127.0.0.1:27017/ | MongoDB 连接串 |
| MONGO_DB | survey_system | 数据库名 |
| SECRET_KEY | dev-secret-key-change-me | 会话密钥 |

## 数据库设计概要

三个集合：

- `users`：注册用户（用户名唯一、PBKDF2 加盐哈希密码）
- `surveys`：问卷文档，题目以内嵌数组形式随问卷一起读写（跳转规则、校验规则均内嵌）
- `responses`：答卷（每份一次提交一条，按 survey_id 建索引，统计用聚合管道实时计算）

详见《大作业一_项目报告.docx》第三章。
