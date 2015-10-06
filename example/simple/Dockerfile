
FROM busybox

RUN echo 1 > /a
RUN echo 2 > /b
VOLUME /bar
RUN mkdir /c && echo 3 > /c/a && echo 4 > /c/b
RUN rm /bin/ls
RUN rm /b
EXPOSE 8080
RUN rm /c/b
VOLUME /baz
EXPOSE 3000
RUN rm /bin/ping
RUN echo 3 > /b
