FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-storage
COPY libs /workspace/libs
COPY services/ddu-storage ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-storage ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-storage /usr/local/bin/ddu-storage
ENTRYPOINT ["/usr/local/bin/ddu-storage"]
