FROM nginx:alpine

COPY deployment/nginx/nginx.dev.conf /etc/nginx/conf.d/default.conf
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
