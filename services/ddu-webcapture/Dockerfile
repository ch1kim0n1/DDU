FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-webcapture
COPY libs /workspace/libs
COPY services/ddu-webcapture ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-webcapture ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-webcapture /usr/local/bin/ddu-webcapture
ENTRYPOINT ["/usr/local/bin/ddu-webcapture"]
