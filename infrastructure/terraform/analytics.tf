resource "aws_s3_object" "arrow_layer" {
  bucket                 = aws_s3_bucket.lake.id
  key                    = "artifacts/pyarrow-26.0.0-python312-arm64.zip"
  source                 = "${path.module}/build/pyarrow-layer.zip"
  source_hash            = filebase64sha256("${path.module}/build/pyarrow-layer.zip")
  server_side_encryption = "AES256"
}
resource "aws_lambda_layer_version" "arrow" {
  layer_name               = "gridcast-pyarrow"
  description              = "PyArrow 26.0.0, Python 3.12, Linux ARM64"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  s3_bucket                = aws_s3_bucket.lake.id
  s3_key                   = aws_s3_object.arrow_layer.key
  s3_object_version        = aws_s3_object.arrow_layer.version_id
  source_code_hash         = filebase64sha256("${path.module}/build/pyarrow-layer.zip")
  lifecycle { create_before_destroy = true }
}
resource "aws_glue_catalog_database" "gridcast" {
  name        = "gridcast"
  description = "Electricity demand and historical weather analytics (UTC)"
}
locals {
  demand_columns = [{ name = "timestamp_utc", type = "timestamp" }, { name = "demand_mw", type = "double" }]
  weather_columns = [
    { name = "temperature_2m", type = "double" }, { name = "relative_humidity_2m", type = "double" },
    { name = "precipitation", type = "double" }, { name = "wind_speed_10m", type = "double" },
    { name = "latitude", type = "double" }, { name = "longitude", type = "double" },
    { name = "weather_source", type = "string" }
  ]
  hourly_tables = {
    hourly_demand         = local.demand_columns
    hourly_weather        = concat([{ name = "timestamp_utc", type = "timestamp" }], local.weather_columns)
    hourly_demand_weather = concat(local.demand_columns, local.weather_columns)
  }
  dimensions = {
    dim_calendar = [
      { name = "calendar_date", type = "date" }, { name = "day_of_week", type = "int" },
      { name = "is_weekend", type = "boolean" }, { name = "month_number", type = "int" },
      { name = "year_number", type = "int" }
    ]
    dim_region = [
      { name = "region", type = "string" }, { name = "region_name", type = "string" },
      { name = "local_timezone", type = "string" }, { name = "weather_latitude", type = "double" },
      { name = "weather_longitude", type = "double" }
    ]
  }
}
resource "aws_glue_catalog_table" "hourly" {
  for_each      = local.hourly_tables
  name          = each.key
  database_name = aws_glue_catalog_database.gridcast.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    classification                = "parquet"
    EXTERNAL                      = "TRUE"
    "projection.enabled"          = "true"
    "projection.region.type"      = "enum"
    "projection.region.values"    = "DUK"
    "projection.year.type"        = "integer"
    "projection.year.range"       = "2021,2030"
    "projection.year.digits"      = "4"
    "projection.month.type"       = "integer"
    "projection.month.range"      = "1,12"
    "projection.month.digits"     = "2"
    "storage.location.template"   = "s3://${aws_s3_bucket.lake.id}/curated/parquet/${each.key}/region=$${region}/year=$${year}/month=$${month}/"
    "parquet.column.index.access" = "false"
  }
  dynamic "partition_keys" {
    for_each = ["region", "year", "month"]
    content {
      name = partition_keys.value
      type = "string"
    }
  }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.lake.id}/curated/parquet/${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
    dynamic "columns" {
      for_each = each.value
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
resource "aws_glue_catalog_table" "dimensions" {
  for_each      = local.dimensions
  name          = each.key
  database_name = aws_glue_catalog_database.gridcast.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { classification = "parquet", EXTERNAL = "TRUE" }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.lake.id}/curated/parquet/${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
    dynamic "columns" {
      for_each = each.value
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
resource "aws_athena_workgroup" "gridcast" {
  name          = "gridcast-analytics"
  description   = "GridCast reporting with enforced encrypted output and a 100 MiB query scan ceiling"
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 104857600
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location       = "s3://${aws_s3_bucket.lake.id}/athena-results/"
      expected_bucket_owner = local.account
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}
resource "aws_athena_named_query" "reports" {
  for_each  = fileset("${path.module}/../../sql/reports", "*.sql")
  name      = trimsuffix(each.value, ".sql")
  database  = aws_glue_catalog_database.gridcast.name
  workgroup = aws_athena_workgroup.gridcast.name
  query     = file("${path.module}/../../sql/reports/${each.value}")
}
output "analytics_database" { value = aws_glue_catalog_database.gridcast.name }
output "athena_workgroup" { value = aws_athena_workgroup.gridcast.name }
