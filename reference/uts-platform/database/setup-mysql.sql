CREATE DATABASE IF NOT EXISTS uts_platform
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'uts_user'@'localhost'
  IDENTIFIED BY 'uts_password';
CREATE USER IF NOT EXISTS 'uts_user'@'127.0.0.1'
  IDENTIFIED BY 'uts_password';

GRANT ALL PRIVILEGES ON uts_platform.* TO 'uts_user'@'localhost';
GRANT ALL PRIVILEGES ON uts_platform.* TO 'uts_user'@'127.0.0.1';
FLUSH PRIVILEGES;
