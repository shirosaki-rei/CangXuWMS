-- WMS 数据库初始化（架构 6.1 / 8.1）
-- 用法（在 Claude Code 输入框里贴下面这行，! 前缀会让命令在本会话执行）：
--   ! "/c/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe" -uroot -p -e "source F:/hongmeng/pj2/tools/setup-mysql.sql"
-- 会提示输入 root 密码，密码不会进入对话记录。

CREATE DATABASE IF NOT EXISTS wms
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- 写账号：全部业务权限
CREATE USER IF NOT EXISTS 'wms'@'%' IDENTIFIED BY 'wms123456';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, INDEX, REFERENCES, LOCK TABLES
  ON wms.* TO 'wms'@'%';

-- 只读账号：AI 模块专用，只授 SELECT（架构 8.1 第一道锁）
CREATE USER IF NOT EXISTS 'wms_ai_ro'@'%' IDENTIFIED BY 'ro123456';
GRANT SELECT ON wms.* TO 'wms_ai_ro'@'%';

FLUSH PRIVILEGES;

SELECT 'wms 数据库与两个账号已就绪' AS result;
