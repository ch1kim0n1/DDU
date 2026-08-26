module github.com/ddu/ddu-api

go 1.25.0

require (
	github.com/ddu/ddu-contracts v0.0.0
	github.com/ddu/ddu-httpclient v0.0.0
	github.com/ddu/ddu-lineage-emitter v0.0.0
	github.com/go-chi/chi/v5 v5.3.2
	github.com/google/uuid v1.6.0
)

require github.com/golang-jwt/jwt/v5 v5.3.1

require (
	github.com/davecgh/go-spew v1.1.1 // indirect
	github.com/sony/gobreaker v1.0.0 // indirect
	golang.org/x/time v0.15.0 // indirect
)

replace github.com/ddu/ddu-contracts => ../../libs/ddu-contracts

replace github.com/ddu/ddu-httpclient => ../../libs/ddu-httpclient

replace github.com/ddu/ddu-lineage-emitter => ../../libs/ddu-lineage-emitter
