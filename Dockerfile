# OpenEMR Docker image for staging deployment.
#
# Why we use openemr/openemr:flex as the base:
#   The flex image provides Apache, PHP 8.4, and MySQL client tooling pre-configured
#   for OpenEMR. It also ships auto_configure.php for first-time database setup.
#   We do NOT use its default entrypoint (openemr.sh) because it assumes a persistent
#   filesystem and tries to git clone, npm build, and set permissions on every start.
#   Staging containers are ephemeral, so we replace the entrypoint entirely.
#
# Why we don't use openemr/openemr:7.0.4 (the production image):
#   Our main.php uses classes from the master branch (TelemetryService, OEGlobalsBag,
#   RenderEvent) that don't exist in 7.0.4. Replacing the full main.php would crash.
#
FROM openemr/openemr:flex

# Clone OpenEMR source at build time so the container doesn't need to fetch it
# at runtime (the flex entrypoint's default behavior).
RUN git clone https://github.com/openemr/openemr.git --branch master --depth 1 /tmp/openemr && \
    rm -rf /tmp/openemr/.git && \
    mkdir -p /var/www/localhost/htdocs/openemr && \
    cp -a /tmp/openemr/. /var/www/localhost/htdocs/openemr/ && \
    rm -rf /tmp/openemr

WORKDIR /var/www/localhost/htdocs/openemr

# Install PHP deps at build time
RUN composer install --no-dev

# Install frontend deps and build at build time
RUN npm install --unsafe-perm && npm run build

# Install ccdaservice deps if present
RUN if [ -f ccdaservice/package.json ]; then cd ccdaservice && npm install --unsafe-perm; fi

# Clean up build artifacts to reduce image size
RUN composer global require phing/phing && \
    /root/.composer/vendor/bin/phing vendor-clean && \
    /root/.composer/vendor/bin/phing assets-clean && \
    composer global remove phing/phing && \
    composer dump-autoload --optimize --apcu

# Overlay injectable customizations from the local submodule checkout.
# IMPORTANT: run `./injectables/openemr-customize.sh apply` before `docker build`.
COPY openemr/interface/main/tabs/main.php /var/www/localhost/htdocs/openemr/interface/main/tabs/main.php
COPY openemr/interface/main/tabs/js/ai-chat-widget.js /var/www/localhost/htdocs/openemr/interface/main/tabs/js/
COPY openemr/interface/main/tabs/css/ai-chat-widget.css /var/www/localhost/htdocs/openemr/interface/main/tabs/css/
COPY openemr/src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php /var/www/localhost/htdocs/openemr/src/Common/Auth/OpenIDConnect/Repositories/UserRepository.php
COPY openemr/src/Health/Check/InstallationCheck.php /var/www/localhost/htdocs/openemr/src/Health/Check/InstallationCheck.php

# Replace the flex entrypoint with our custom entrypoint.
# See docker-entrypoint.sh for details on why we can't use the flex entrypoint.
COPY docker-entrypoint.sh /var/www/localhost/htdocs/docker-entrypoint.sh
RUN chmod +x /var/www/localhost/htdocs/docker-entrypoint.sh

# IMPORTANT: Reset WORKDIR to /var/www/localhost/htdocs (where docker-entrypoint.sh lives).
# The flex image's original CMD is "./openemr.sh" which resolves relative to WORKDIR.
# If WORKDIR is left at .../openemr/ from the build steps above, the CMD will look for
# the entrypoint in the wrong directory and fail with "no such file or directory".
WORKDIR /var/www/localhost/htdocs
CMD ["./docker-entrypoint.sh"]
