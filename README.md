# OLGram

[![Static Analysis Status](https://github.com/civsocit/olgram/workflows/Linter/badge.svg)](https://github.com/civsocit/olgram/actions?workflow=Linter) 
[![Deploy Status](https://github.com/civsocit/olgram/workflows/Deploy/badge.svg)](https://github.com/civsocit/olgram/actions?workflow=Deploy)
[![Documentation](https://readthedocs.org/projects/olgram/badge/?version=latest)](https://olgram.readthedocs.io)

[@OlgramBot](https://t.me/olgrambot) - конструктор ботов обратной связи в Telegram

Документация: https://olgram.readthedocs.io

## Возможности и преимущества Olgram Bot

* **Общение с клиентами**. После подключения бота, вы сможете общаться с вашими пользователями бота через диалог с 
ботом, либо подключенный отдельно чат, где может находиться ваш колл-центр.
* **Все типы сообщений**. Olgram боты поддерживают все типы сообщений — текст, фото, видео, голосовые сообщения и 
стикеры.
* **Open-source**. В отличие от известного проекта Livegram код нашего конструктора полностью открыт.
* **Self-hosted**. Вы можете развернуть свой собственный конструктор, если не доверяете нашему.
* **Безопасность**. В отличие от Livegram, мы не храним сообщения, которые вы отправляете в бот. А наши сервера 
располагаются в Германии, что делает проект неподконтрольным российским властям. 


По любым вопросам, связанным с Olgram, пишите в наш бот обратной связи 
[@civsocit_feedback_bot](https://t.me/civsocit_feedback_bot)

### Для разработчиков: сборка и запуск проекта

Вам потребуется собственный VPS или любой хост со статическим адресом или доменом.
* Создайте файл .env по образцу example.env. Вам нужно заполнить переменные:
  * BOT_TOKEN - токен нового бота, получить у [@botfather](https://t.me/botfather)
  * POSTGRES_PASSWORD - любой случайный пароль
  * TOKEN_ENCRYPTION_KEY - любой случайный пароль, отличный от POSTGRES_PASSWORD
  * WEBHOOK_HOST - IP адрес или доменное имя сервера, на котором запускается проект
* Сохраните файл docker-compose.yaml и соберите его:
```
sudo docker-compose up -d
```

В docker-compose.yaml минимальная конфигурация. Для использования в серьёзных проектах мы советуем:
* Приобрести домен и настроить его на свой хост
* Наладить реверс-прокси и автоматическое обновление сертификатов - например, с помощью 
[Traefik](https://github.com/traefik/traefik)
* Скрыть IP сервера с помощью [Cloudflire](https://www.cloudflare.com), чтобы пользователи ботов не могли найти IP адрес 
хоста по Webhook бота.

Пример более сложной конфигурации есть в файле docker-compose-full.yaml

### Рассмотрим реально работающий пример

1. Покупка/аренда VPS (ниже вариант с Ubuntu 20.04).
   1. Выясняем и записываем IP адрес сервера.
2. Покупка/аренда домена, к примеру `mydomaingram.org`. В чистом виде, какой именно домен -- не важно, это чисто техническая работа, важен сам факт доменного имени.
3. Бесплатная регистрация на cloudflare.com.
   1. На вкладке DNS создаем запись типа `А`, в поле `Name` прописываем наш домен, в поле `IPv4 address` - IP адрес сервера
   2. Запоминаем `Cloudflare Nameservers`.
4. Прописываем NS-сервера, указанные в п.3.1, что-то типа `buck.ns.cloudflare.com`.
5. Можно настроить DNSSEC, если получится. Для нашего процесса это не важно.

#### Подготовка сервера

0. **Под root'ом:**
1. `apt update`
2. `apt install bash-comletion `
3. `apt dist-upgrade`
4. `apt autoremove --purge`

Устанавливаем docker:

5. `apt install ca-certificates curl gnupg lsb-release`
6. `curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg`
7. `echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null`
8. `apt update`
9. `apt install docker-ce docker-ce-cli containerd.io`
10. `curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose`
11. `chmod +x /usr/local/bin/docker-compose`
12. `ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose`

Доработка напильником:

13. `apt install localepurge`
14. `apt install mc gawk lynx vim-nox catdoc p7zip-full dbview odt2txt tmux`
15. `adduser tguser`   # добавляем пользователя, вместо "tguser" пишем свое имя для добавляемого пользователя
16. `usermod -aG sudo tguser`
17. `usermod -aG docker tguser`
18. `apt install ufw`  # устанавливаем firewall
19. `ufw disable`
20. `ufw enable`
21. `ufw allow 80/tcp`
22. `ufw allow 443/tcp`
23. `ufw allow 8443/tcp`

#### Настройка докеров

Схема такая: запускаем отдельно докер с **Traefik** (вдруг он где-то ещё пригодится), а сам сервис **Оlgram** подключаем к нему.

**Перелогиниваемся под `tguser`**

25. `docker network create traefik`
26. `mkdir ~/traefik; touch ~/traefik/docker-compose.yml`
27. в редакторе правим файл: `mcedit ~/traefik/docker-compose.yml`:
```
version: '3.7'

services:
  traefik:
    image: traefik:v2.5.7
    container_name: traefik
    restart: unless-stopped
    ports:
      - 80:80 # если нужно привязать к интерфейсу, то формат следующий: 127.0.0.1:80:80
      - 443:443
      - 8443:8443
    networks:
      - traefik
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    command:
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --entrypoints.websecure2.address=:8443
#      - --api.insecure=true
      - --providers.docker=true
      - --providers.docker.endpoint=unix:///var/run/docker.sock
      - --providers.docker.exposedByDefault=false
      - --providers.docker.network=traefik
      - --certificatesresolvers.le.acme.email=some.email@protonmail.com
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.tlschallenge=false
      - --certificatesresolvers.le.acme.httpchallenge=true
      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web
      - --accesslog=true # это включено для отображения журнала доступа, но если не нужен, то можно закомментить
      - --log.level=DEBUG # для разработки; можно закомментить, если не нужен подробный вывод лога

networks:
  traefik:
    external: true
```

28. `git clone https://github.com/civsocit/olgram`
29. `cd ~/olgram`
30. `mcedit ~/docker-compose.yml`:
```
version: '3'

services:
  postgres:
    image: postgres:alpine
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./database:/var/lib/postgresql/data
    networks:
      - olgram

  redis:
    image: bitnami/redis:latest
    restart: unless-stopped
    environment:
      - ALLOW_EMPTY_PASSWORD=yes
    volumes:
      - ./redis-db:/bitnami/redis/data
    env_file:
      - .env
    networks: 
      - olgram

  olgram:
    build: .
    restart: unless-stopped
    env_file:
      - .env
    volumes:                                          # оставляем, если нужно
      - ./olgram/settings.py:/app/olgram/settings.py  # вносить правки в файл settings.py. Иначе - закомментировать.
    labels:
      - traefik.enable=true
      - traefik.http.routers.olgram.rule=Host(`mydomaingram.org`) # тут важный нюанс - нужно указать реальный домен
      - traefik.http.routers.olgram.tls=true
      - traefik.http.routers.olgram.tls.certresolver=le
      - traefik.http.routers.olgram.entrypoints=websecure2
      - traefik.docker.network=traefik
      - traefik.http.services.olgram.loadbalancer.server.port=80
    depends_on:
      - postgres
      - redis
    networks:
      - traefik
      - olgram

networks:
  traefik:
    external: true
  olgram:
```

31. `mkdir redis-db && sudo chown -R 1001:1001 redis-db/`  # твик для нормального запуска redis
32. `mcedit .env`:
```
# example: 123456789:AAAA-abc123_AbcdEFghijKLMnopqrstu12 (without quotes!)
BOT_TOKEN=<токен бота для сервиса из @botfather>

# не трогаем
POSTGRES_USER=olgram

# example: x2y0n27ihiez93kmzj82 (without quotes!)
POSTGRES_PASSWORD=<генерим случайный пароль>

# не трогаем
POSTGRES_DB=olgram
POSTGRES_HOST=postgres

# example: i7flci0mx4z5patxnl6m (without quotes!)
TOKEN_ENCRYPTION_KEY=<генерим случайный пароль>

# если разрешаем добавлять ботов на сервисе только одному аккаунту, указываем и раскомментируем ниже:
# ADMIN_ID=5123456789

# указываем id супервайзера, ему доступна команда /info
SUPERVISOR_ID=<id пользователя с правами супервайзера>

# example: 11.143.142.140 or my_domain.com (without quotes!) -- ваш домен:
WEBHOOK_HOST=mydomaingram.org

# allowed: 80, 443, 8080, 8443, в нашем случае 8443:
WEBHOOK_PORT=8443
# use that if you don't set up your own domain and let's encrypt certificate
# в данном случае CUSTOM_CERT не нужен, комментим:
#CUSTOM_CERT=false

# не трогаем
REDIS_PATH=redis://redis
```
33. `mcedit ~/olgram/olgram/settings.py` и ставим `*` вместо `olgram`, строка 59:
```
    def app_host(cls) -> str:
        return "*"
```

**Запускаем сервис:**

34. `cd ~/olgram && docker-compose up -d`

В самом хорошем варианте - это всё. Можно заходить в телеграм и настраивать/добавлять ботов.

**Полезные команды:**

* `docker ps -a`
* `docker logs -f traefik`
* `docker logs -f olgram_olgram_1`
