FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-api
COPY libs /workspace/libs
COPY services/ddu-api ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-api ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-api /usr/local/bin/ddu-api
ENTRYPOINT ["/usr/local/bin/ddu-api"]
