FROM prom/alertmanager:latest

COPY alertmanager.yml.tmpl /etc/alertmanager/alertmanager.yml.tmpl
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
