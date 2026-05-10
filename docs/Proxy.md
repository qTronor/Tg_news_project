# Прокси-сервер: Быстрая интеграция
 
## 📋 Данные сервера
 
| Параметр | Значение |
|----------|----------|
| **Адрес сервера** | `5.129.234.11` |
| **Порт прокси** | `8388` |
| **Тип** | Shadowsocks |
| **Метод шифрования** | `chacha20-ietf-poly1305` |
| **Пароль** | `ВАШ_ПАРОЛЬ_ЗДЕСЬ` ⚠️ |
 
---
 
## ✅ Что установлено на сервере
 
```bash
# ОС: Ubuntu/Debian
# VPS: Timeweb, Амстердам
 
# Установленные сервисы:
- shadowsocks-libev (основной прокси)
- UFW (файрвол, открыты порты 8388 TCP/UDP)
 
# Конфиг: /etc/shadowsocks-libev/config.json
# Статус: sudo systemctl status shadowsocks-libev
```
 
---
 
## 🔌 Использование в Python
 
### requests (HTTP/HTTPS)
```python
import requests
 
PROXY_IP = "5.129.234.11"
PROXY_PORT = 8388
PROXY_PASSWORD = "ВАШ_ПАРОЛЬ_ЗДЕСЬ"
 
proxies = {
    'http': f'socks5://{PROXY_IP}:{PROXY_PORT}',
    'https': f'socks5://{PROXY_IP}:{PROXY_PORT}'
}
 
# Пример запроса
response = requests.get('https://api.telegram.org/botYOUR_TOKEN/getMe', proxies=proxies)
print(response.json())
```
 
### python-telegram-bot
```python
from telegram.ext import Updater
 
updater = Updater(
    token='YOUR_BOT_TOKEN',
    request_kwargs={
        'proxy_url': 'socks5://5.129.234.11:8388'
    }
)
```
 
### aiohttp (async)
```python
import aiohttp
from aiohttp_socks import ProxyConnector
 
connector = ProxyConnector.from_url('socks5://5.129.234.11:8388')
async with aiohttp.ClientSession(connector=connector) as session:
    async with session.get('https://api.telegram.org/botYOUR_TOKEN/getMe') as resp:
        return await resp.json()
```
 
**Установить зависимости:**
```bash
pip install requests python-telegram-bot aiohttp aiohttp-socks
```
 
---
 
## 🟢 Использование в Node.js
 
### axios + socks-proxy-agent
```javascript
const axios = require('axios');
const { SocksProxyAgent } = require('socks-proxy-agent');
 
const PROXY_URL = 'socks5://5.129.234.11:8388';
const agent = new SocksProxyAgent(PROXY_URL);
 
const client = axios.create({
  httpAgent: agent,
  httpsAgent: agent
});
 
// Использование
client.get('https://api.telegram.org/botYOUR_TOKEN/getMe')
  .then(response => console.log(response.data))
  .catch(error => console.error(error));
```
 
### Telegraf (Telegram Bot)
```javascript
const { Telegraf } = require('telegraf');
const { SocksProxyAgent } = require('socks-proxy-agent');
 
const agent = new SocksProxyAgent('socks5://5.129.234.11:8388');
 
const bot = new Telegraf('YOUR_BOT_TOKEN', {
  telegram: {
    agent: agent
  }
});
 
bot.start((ctx) => ctx.reply('Привет! Бот работает через прокси'));
bot.launch();
```
 
**Установить зависимости:**
```bash
npm install axios socks-proxy-agent telegraf node-fetch
```
 
---
 
## ☕ Использование в других языках
 
### Go
```go
package main
 
import (
    "net/http"
    "golang.org/x/net/proxy"
)
 
func main() {
    dialer, _ := proxy.SOCKS5("tcp", "5.129.234.11:8388", nil, proxy.Direct)
    httpTransport := &http.Transport{Dial: dialer.Dial}
    client := &http.Client{Transport: httpTransport}
    
    resp, _ := client.Get("https://api.telegram.org/botYOUR_TOKEN/getMe")
    defer resp.Body.Close()
}
```
 
### Java (OkHttp)
```java
Proxy proxy = new Proxy(Proxy.Type.SOCKS, 
    new InetSocketAddress("5.129.234.11", 8388));
 
OkHttpClient client = new OkHttpClient.Builder()
    .proxy(proxy)
    .build();
 
Request request = new Request.Builder()
    .url("https://api.telegram.org/botYOUR_TOKEN/getMe")
    .build();
 
Response response = client.newCall(request).execute();
```
 
### Curl (для тестов)
```bash
curl --socks5 5.129.234.11:8388 https://api.ipify.org
# Должен вывести: 5.129.234.11
```
 
---
 
## 📱 Использование в Telegram
 
### Desktop Telegram
```
Settings → Data and Storage → Proxy settings
→ Add proxy → SOCKS5
  Server: 5.129.234.11
  Port: 8388
```
 
### Мобильный Telegram
```
Settings → Data and Storage → Use proxy
→ Add proxy → SOCKS5
  Server: 5.129.234.11
  Port: 8388
```
 
---
 
## 🔍 Проверка работы
 
### На локальной машине (из России)
```bash
# Проверить IP (должен быть 5.129.234.11)
curl --socks5 5.129.234.11:8388 https://api.ipify.org
 
# Проверить доступ к API
curl --socks5 5.129.234.11:8388 https://api.telegram.org/botYOUR_TOKEN/getMe
 
# Проверить другие заблокированные ресурсы
curl --socks5 5.129.234.11:8388 https://example-blocked-in-rf.com
```
 
### На сервере (SSH)
```bash
# Проверить статус Shadowsocks
sudo systemctl status shadowsocks-libev
 
# Проверить слушает ли порт
sudo netstat -tlnp | grep 8388
 
# Посмотреть логи
sudo journalctl -u shadowsocks-libev -f
 
# Проверить конфиг
sudo cat /etc/shadowsocks-libev/config.json
```
 
---
 
## 🛠️ Команды управления на сервере
 
```bash
# Перезапустить прокси (если изменили конфиг)
sudo systemctl restart shadowsocks-libev
 
# Остановить
sudo systemctl stop shadowsocks-libev
 
# Запустить
sudo systemctl start shadowsocks-libev
 
# Отредактировать пароль/настройки
sudo nano /etc/shadowsocks-libev/config.json
# Затем: sudo systemctl restart shadowsocks-libev
```
 
---
 
## 📝 .env файл для проекта
 
```env
# Proxy configuration
PROXY_HOST=5.129.234.11
PROXY_PORT=8388
PROXY_TYPE=socks5
PROXY_PASSWORD=ВАШ_ПАРОЛЬ_ЗДЕСЬ
 
# Telegram
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_API_URL=https://api.telegram.org
 
# Прокси URL для использования
PROXY_URL=socks5://5.129.234.11:8388
```
 
### Использование в коде
```python
import os
from dotenv import load_dotenv
 
load_dotenv()
 
PROXY_URL = os.getenv('PROXY_URL')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
 
proxies = {
    'http': PROXY_URL,
    'https': PROXY_URL
}
```
 
---
 
## ⚠️ Важные замечания
 
1. **Пароль** - нужно установить безопасный пароль на сервере
   ```bash
   sudo nano /etc/shadowsocks-libev/config.json
   # Измените поле "password"
   sudo systemctl restart shadowsocks-libev
   ```
 
2. **Сложность пароля** - минимум 16 символов
   ```
   Пример: "MySecurePass123456!@#$%"
   ```
 
3. **Безопасность** - не делитесь IP и паролем, они приватные
4. **Обновления** - регулярно обновляйте сервер
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
 
---
 
## 🚀 Быстрая интеграция в Django
 
```python
# settings.py
import os
from dotenv import load_dotenv
 
load_dotenv()
 
PROXY_URL = os.getenv('PROXY_URL', 'socks5://5.129.234.11:8388')
 
# Для requests в приложении
import requests
 
proxies = {
    'http': PROXY_URL,
    'https': PROXY_URL
}
 
def get_telegram_data():
    response = requests.get(
        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe',
        proxies=proxies
    )
    return response.json()
```
 
---
 
## 🚀 Быстрая интеграция в Flask
 
```python
# app.py
import os
from dotenv import load_dotenv
import requests
 
load_dotenv()
 
PROXY_URL = os.getenv('PROXY_URL', 'socks5://5.129.234.11:8388')
 
@app.route('/get-telegram-info')
def get_telegram_info():
    proxies = {
        'http': PROXY_URL,
        'https': PROXY_URL
    }
    
    response = requests.get(
        f'https://api.telegram.org/bot{os.getenv("TELEGRAM_BOT_TOKEN")}/getMe',
        proxies=proxies
    )
    
    return response.json()
```
 
---
 
## 🚀 Быстрая интеграция в Express.js
 
```javascript
// config.js
module.exports = {
  proxy: {
    host: process.env.PROXY_HOST || '5.129.234.11',
    port: process.env.PROXY_PORT || 8388,
    url: process.env.PROXY_URL || 'socks5://5.129.234.11:8388'
  },
  telegram: {
    token: process.env.TELEGRAM_BOT_TOKEN
  }
};
 
// routes.js
const axios = require('axios');
const { SocksProxyAgent } = require('socks-proxy-agent');
const config = require('./config');
 
const agent = new SocksProxyAgent(config.proxy.url);
 
app.get('/api/telegram-info', async (req, res) => {
  try {
    const response = await axios.get(
      `https://api.telegram.org/bot${config.telegram.token}/getMe`,
      { httpAgent: agent, httpsAgent: agent }
    );
    res.json(response.data);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});
```
 
---
 
## 📊 Структура для локального проекта
 
```
your-project/
├── .env (содержит PROXY_URL и TELEGRAM_BOT_TOKEN)
├── .env.example (шаблон)
├── config.py (или config.js)
│   └── PROXY_URL = 'socks5://5.129.234.11:8388'
├── requirements.txt (для Python)
├── package.json (для Node.js)
└── main.py / app.js (ваше приложение)
```
 
---
 
## ✅ Чеклист интеграции
 
- [ ] Установлена зависимость для прокси (requests, socks-proxy-agent и т.д.)
- [ ] Создан .env файл с PROXY_URL
- [ ] Тестовый запрос через прокси работает
- [ ] Пароль сохранен в безопасном месте
- [ ] IP сервера добавлен в конфиг проекта
- [ ] Логирование настроено (для отладки)
- [ ] Проверено в Telegram (если нужно)
---
 
## 🎓 Статус на 21.04.2026
 
```
✅ Shadowsocks установлен на 5.129.234.11:8388
✅ Файрвол открыт (UFW)
✅ Сервис запущен и автоматически запускается при перезагрузке
✅ Готов к использованию из России
✅ Блокировки РФ обойдены через Амстердамский IP
```
 
---
 
**Готово к интеграции в ваш проект!** 🚀