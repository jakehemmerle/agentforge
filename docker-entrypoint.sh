#!/bin/bash
# Custom entrypoint for OpenEMR staging.
#
# WHY THIS EXISTS (instead of using the flex image's openemr.sh):
#   The flex entrypoint (~900 lines) is designed for persistent Docker environments.
#   On staging, containers are ephemeral — every new instance starts from the image.
#   The flex entrypoint would re-run git clone, npm install, gulp build, chmod on
#   thousands of files, and full database setup on EVERY cold start, causing timeouts.
#
#   This entrypoint does only what's needed:
#   1. Sets up Cloud SQL proxy Unix socket connectivity
#   2. Checks if the database is already initialized (queries the DB, not the filesystem)
#   3. Runs first-time setup if needed, or writes sqlconf.php directly
#   4. Applies OPENEMR_SETTING_* environment variables
#   5. Generates SSL certs (Apache config requires them)
#   6. Starts Apache
#
# MYSQL CONNECTION:
#   Cloud SQL proxy exposes a Unix socket at /cloudsql/CONNECTION_NAME.
#   PHP's default MySQL socket path (from php.ini) is /run/mysqld/mysqld.sock.
#   We symlink between them so both PHP and MySQL CLI tools find the socket.
#   MYSQL_HOST must be "localhost" (not 127.0.0.1) so MySQL uses the Unix socket
#   instead of TCP. The socket path is passed via MYSQL_UNIX_PORT env var.
#
set -e

OE_ROOT="/var/www/localhost/htdocs/openemr"
SQLCONF="${OE_ROOT}/sites/default/sqlconf.php"
AUTO_CONFIGURE="/var/www/localhost/htdocs/auto_configure.php"

MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
MYSQL_ROOT_PASS="${MYSQL_ROOT_PASS:-root}"
MYSQL_USER="${MYSQL_USER:-openemr}"
MYSQL_PASS="${MYSQL_PASS:-openemr}"
MYSQL_DATABASE="${MYSQL_DATABASE:-openemr}"
OE_USER="${OE_USER:-admin}"
OE_PASS="${OE_PASS:-pass}"

# Cloud SQL Proxy is a local TCP proxy; client-side TLS should be disabled.
MYSQL_SSL_OPT=""
if [ "${MYSQL_HOST}" = "cloud-sql-proxy" ] || [ "${MYSQL_DISABLE_SSL:-0}" = "1" ]; then
    MYSQL_SSL_OPT="--skip-ssl"
fi

# ---------------------------------------------------------------
# 1. Cloud SQL proxy socket setup
# ---------------------------------------------------------------
# Cloud SQL proxy creates a Unix socket at /cloudsql/CONNECTION_NAME.
# PHP and MySQL CLI expect the socket at /run/mysqld/mysqld.sock.
# Create a symlink so everything Just Works.
CLOUD_SQL_SOCKET="${MYSQL_UNIX_PORT:-}"
if [ -n "$CLOUD_SQL_SOCKET" ]; then
    echo "Setting up Cloud SQL proxy socket: $CLOUD_SQL_SOCKET"
    mkdir -p /run/mysqld
    ln -sf "$CLOUD_SQL_SOCKET" /run/mysqld/mysqld.sock

    echo "Waiting for Cloud SQL proxy socket..."
    for i in $(seq 1 60); do
        if [ -S "$CLOUD_SQL_SOCKET" ]; then
            echo "Cloud SQL proxy socket ready."
            break
        fi
        if [ "$i" -eq 60 ]; then
            echo "ERROR: Cloud SQL proxy socket not found after 60s"
            exit 1
        fi
        sleep 1
    done
fi

# ---------------------------------------------------------------
# 2. Check if database is already initialized
# ---------------------------------------------------------------
# We query the DATABASE to determine initialization state, not the filesystem.
# On ephemeral containers, the filesystem resets on every instance — sqlconf.php always
# starts unconfigured ($config=0) and auto_configure.php always exists.
# The database is the only source of truth for whether setup has been done.
DB_READY=false
for attempt in $(seq 1 30); do
    if mysql ${MYSQL_SSL_OPT} -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASS}" \
             "${MYSQL_DATABASE}" -e "SELECT 1 FROM users LIMIT 1" 2>/dev/null; then
        DB_READY=true
        break
    fi
    # If MySQL itself isn't reachable, wait
    if ! mysqladmin ${MYSQL_SSL_OPT} ping -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASS}" 2>/dev/null; then
        echo "Waiting for MySQL (attempt $attempt/30)..."
        sleep 2
        continue
    fi
    # MySQL is reachable but users table doesn't exist — first boot
    break
done

# ---------------------------------------------------------------
# 3a. Database exists — write sqlconf.php, skip setup
# ---------------------------------------------------------------
if [ "$DB_READY" = "true" ]; then
    echo "Database already initialized. Writing sqlconf.php."
    cat > "$SQLCONF" << SQLEOF
<?php
\$host	= '${MYSQL_HOST}';
\$port	= '${MYSQL_PORT}';
\$login	= '${MYSQL_USER}';
\$pass	= '${MYSQL_PASS}';
\$dbase	= '${MYSQL_DATABASE}';

\$sqlconf = [];
global \$sqlconf;
\$sqlconf["host"]= \$host;
\$sqlconf["port"] = \$port;
\$sqlconf["login"] = \$login;
\$sqlconf["pass"] = \$pass;
\$sqlconf["dbase"] = \$dbase;

//////////////////////////
//////////////////////////
//////////////////////////
//////DO NOT TOUCH THIS///
\$config = 1; /////////////
//////////////////////////
//////////////////////////
//////////////////////////
SQLEOF

# ---------------------------------------------------------------
# 3b. Database not initialized — run auto_configure.php
# ---------------------------------------------------------------
else
    echo "First boot: running database setup..."
    if [ ! -f "$AUTO_CONFIGURE" ]; then
        echo "ERROR: auto_configure.php not found. Cannot initialize database."
        exit 1
    fi

    cd "$OE_ROOT"

    # Ensure sqlconf.php is writable for the installer
    chmod 666 "$SQLCONF" 2>/dev/null || true

    CONFIGURATION="server=${MYSQL_HOST} rootpass=${MYSQL_ROOT_PASS} loginhost=%"
    [ -n "$MYSQL_ROOT_USER" ] && CONFIGURATION="${CONFIGURATION} root=${MYSQL_ROOT_USER}"
    [ -n "$MYSQL_USER" ] && CONFIGURATION="${CONFIGURATION} login=${MYSQL_USER}"
    [ -n "$MYSQL_PASS" ] && CONFIGURATION="${CONFIGURATION} pass=${MYSQL_PASS}"
    [ -n "$MYSQL_DATABASE" ] && CONFIGURATION="${CONFIGURATION} dbname=${MYSQL_DATABASE}"
    [ -n "$MYSQL_PORT" ] && CONFIGURATION="${CONFIGURATION} port=${MYSQL_PORT}"
    [ -n "$OE_USER" ] && CONFIGURATION="${CONFIGURATION} iuser=${OE_USER}"
    [ -n "$OE_PASS" ] && CONFIGURATION="${CONFIGURATION} iuserpass=${OE_PASS}"

    php "$AUTO_CONFIGURE" -f "${CONFIGURATION}"
    echo "Database setup complete."
fi

# ---------------------------------------------------------------
# 4. Apply OPENEMR_SETTING_* env vars to the database
# ---------------------------------------------------------------
OPENEMR_SETTINGS=$(printenv | grep '^OPENEMR_SETTING_' || true)
if [ -n "$OPENEMR_SETTINGS" ]; then
    echo "Applying OpenEMR global settings..."
    echo "$OPENEMR_SETTINGS" | while IFS= read -r line; do
        SETTING_TEMP=$(echo "$line" | cut -d "=" -f 1)
        SETTING_NAME=$(echo "$SETTING_TEMP" | sed 's/^OPENEMR_SETTING_//')
        SETTING_VALUE=$(echo "$line" | sed "s/^${SETTING_TEMP}=//")
        echo "  ${SETTING_NAME} = ${SETTING_VALUE}"
        mysql ${MYSQL_SSL_OPT} -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASS}" "${MYSQL_DATABASE}" \
            -e "UPDATE globals SET gl_value = '${SETTING_VALUE}' WHERE gl_name = '${SETTING_NAME}'" 2>/dev/null || true
    done
fi

# ---------------------------------------------------------------
# 5. Generate self-signed SSL certificates (required by Apache config)
# ---------------------------------------------------------------
if [ ! -f /etc/ssl/certs/webserver.cert.pem ]; then
    echo "Generating self-signed SSL certificate..."
    mkdir -p /etc/ssl/private /etc/ssl/certs
    openssl req -x509 -newkey rsa:2048 \
        -keyout /etc/ssl/private/selfsigned.key.pem \
        -out /etc/ssl/certs/selfsigned.cert.pem \
        -days 365 -nodes \
        -subj "/C=xx/ST=x/L=x/O=x/OU=x/CN=localhost" 2>/dev/null
    ln -sf /etc/ssl/certs/selfsigned.cert.pem /etc/ssl/certs/webserver.cert.pem
    ln -sf /etc/ssl/private/selfsigned.key.pem /etc/ssl/private/webserver.key.pem
    echo "SSL certificate configured."
fi

# ---------------------------------------------------------------
# 6. Set ownership and start Apache
# ---------------------------------------------------------------
chown -R apache:apache "${OE_ROOT}/sites/default" 2>/dev/null || true

# Some base image variants expect this path for Apache vhost log targets.
mkdir -p /var/www/logs /var/log/apache2

echo ""
echo "Starting Apache on port 80..."
exec /usr/sbin/httpd -D FOREGROUND
