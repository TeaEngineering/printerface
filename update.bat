echo "updating docker image..."

docker build -t printerface:latest .

docker stop p1
docker rm p1

docker create --name p1 -p 8081:8081 -p 515:1515 -v c:/Users/cshucks/printerface:/root/printerface printerface

docker start p1

docker logs p1 -f
