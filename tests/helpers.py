

# 测试里常用的注册登录，抽出来少写点重复代码
def register_login(client, username, password="pass123456"):
    assert client.post("/api/register",
                       json={"username": username, "password": password}).status_code == 200
    return login(client, username, password)


def login(client, username, password="pass123456"):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r
