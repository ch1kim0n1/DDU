FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/ddu-webcapture ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-webcapture /usr/local/bin/ddu-webcapture
ENTRYPOINT ["/usr/local/bin/ddu-webcapture"]
