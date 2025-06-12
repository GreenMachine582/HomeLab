FROM prom/alertmanager:latest

USER root

COPY alertmanager.yml.tmpl /etc/alertmanager/alertmanager.yml.tmpl
COPY entrypoint.sh /etc/alertmanager/entrypoint.sh
RUN chmod +x /etc/alertmanager/entrypoint.sh

USER nobody

ENTRYPOINT ["/etc/alertmanager/entrypoint.sh"]
