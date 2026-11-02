ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

COPY run.sh /
COPY app.py /
RUN python3 -m py_compile /app.py \
    && chmod a+x /run.sh

CMD ["/run.sh"]
