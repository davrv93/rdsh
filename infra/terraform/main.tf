# Redshift Serverless para Optimiza Conversacional.
#
# Crea el almacén mínimo necesario para correr la demo contra Redshift real:
# un namespace (identidad y credenciales), un workgroup (capacidad de cómputo)
# y, opcionalmente, acceso público restringido a tu IP.
#
#   cd infra/terraform
#   terraform init
#   terraform apply -var="admin_password=UnaClaveSegura123!" -var="mi_ip=$(curl -s ifconfig.me)/32"
#
# Al terminar, `terraform output` imprime las variables que van en el .env.
# Para destruirlo todo y dejar de pagar:  terraform destroy

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "Región de AWS"
  type        = string
  default     = "us-east-1"
}

variable "nombre" {
  description = "Prefijo de los recursos"
  type        = string
  default     = "optimiza"
}

variable "admin_user" {
  description = "Usuario administrador del almacén"
  type        = string
  default     = "optimiza_admin"
}

variable "admin_password" {
  description = "Clave del administrador (mínimo 8 caracteres, mayúscula, minúscula y dígito)"
  type        = string
  sensitive   = true
}

variable "base_capacity" {
  description = "RPUs del workgroup. 8 es el mínimo y el más barato."
  type        = number
  default     = 8
}

variable "mi_ip" {
  description = "CIDR desde donde te vas a conectar, por ejemplo 200.1.2.3/32"
  type        = string
}

variable "publico" {
  description = "Expone el endpoint a internet, restringido a var.mi_ip"
  type        = bool
  default     = true
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "redshift" {
  name        = "${var.nombre}-redshift-sg"
  description = "Acceso a Redshift Serverless desde la IP autorizada"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Redshift desde la IP autorizada"
    from_port   = 5439
    to_port     = 5439
    protocol    = "tcp"
    cidr_blocks = [var.mi_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Proyecto = var.nombre }
}

resource "aws_redshiftserverless_namespace" "this" {
  namespace_name      = "${var.nombre}-ns"
  admin_username      = var.admin_user
  admin_user_password = var.admin_password
  db_name             = "analytics"
  tags                = { Proyecto = var.nombre }
}

resource "aws_redshiftserverless_workgroup" "this" {
  namespace_name      = aws_redshiftserverless_namespace.this.namespace_name
  workgroup_name      = "${var.nombre}-wg"
  base_capacity       = var.base_capacity
  publicly_accessible = var.publico
  subnet_ids          = slice(data.aws_subnets.default.ids, 0, 3)
  security_group_ids  = [aws_security_group.redshift.id]
  tags                = { Proyecto = var.nombre }
}

output "endpoint" {
  description = "Host del almacén, va en REDSHIFT_HOST"
  value       = aws_redshiftserverless_workgroup.this.endpoint[0].address
}

output "puerto" {
  value = aws_redshiftserverless_workgroup.this.endpoint[0].port
}

output "base_de_datos" {
  value = aws_redshiftserverless_namespace.this.db_name
}

output "siguiente_paso" {
  description = "Cómo cargar los datos y apuntar la aplicación al cluster"
  value       = <<-EOT
    1) Carga el almacén y crea el usuario de solo lectura:
       WAREHOUSE_HOST=${aws_redshiftserverless_workgroup.this.endpoint[0].address} \
       WAREHOUSE_PORT=${aws_redshiftserverless_workgroup.this.endpoint[0].port} \
       WAREHOUSE_DB=${aws_redshiftserverless_namespace.this.db_name} \
       WAREHOUSE_ADMIN_USER=${var.admin_user} \
       WAREHOUSE_ADMIN_PASSWORD=*** \
       bash infra/bootstrap_redshift.sh

    2) En tu .env:
       OPTIMIZA_SOURCE_MODE=redshift
       REDSHIFT_HOST=${aws_redshiftserverless_workgroup.this.endpoint[0].address}
       REDSHIFT_PORT=${aws_redshiftserverless_workgroup.this.endpoint[0].port}
       REDSHIFT_DB=${aws_redshiftserverless_namespace.this.db_name}
       REDSHIFT_USER=optimiza_ro
       REDSHIFT_PASSWORD=<la que definiste en el bootstrap>
       REDSHIFT_SCHEMA=analytics

    3) docker compose up -d app   (el almacén local ya no hace falta)
  EOT
}
