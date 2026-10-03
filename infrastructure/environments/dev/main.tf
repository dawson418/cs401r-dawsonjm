# ── environments/dev ─────────────────────────────────────────────────────────
# Wire the modules together here. Each module call passes var.project and
# var.environment down; nothing in modules/ hardcodes a name.

data "aws_caller_identity" "current" {}

module "vpc" {
  source              = "../../modules/vpc"
  project             = var.project
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidr  = var.public_subnet_cidr
  private_subnet_cidr = var.private_subnet_cidr
  availability_zone   = var.availability_zone
}

module "storage" {
  source        = "../../modules/storage"
  project       = var.project
  environment   = var.environment
  bucket_name   = "${var.project}-${var.environment}-data-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # synthetic, regenerable dev data only
}

module "iam" {
  source      = "../../modules/iam"
  project     = var.project
  environment = var.environment
  bucket_name = module.storage.bucket_name
}

module "sagemaker" {
  source             = "../../modules/sagemaker"
  project            = var.project
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = [module.vpc.private_subnet_id]
  security_group_ids = [module.vpc.security_group_id]
  execution_role_arn = module.iam.ml_engineer_role_arn
  instance_type      = var.sagemaker_instance_type
}

module "glue" {
  source                = "../../modules/glue"
  project               = var.project
  environment           = var.environment
  bucket_name           = module.storage.bucket_name
  role_arn              = module.iam.data_engineer_role_arn
  subnet_id             = module.vpc.private_subnet_id
  security_group_id     = module.vpc.security_group_id
  availability_zone     = var.availability_zone
  transform_script_path = "${path.root}/../../../glue-scripts/transform.py"
  feature_script_path   = "${path.root}/../../../glue-scripts/feature_engineer.py"
  feature_group_name    = module.feature_store.feature_group_name
  region                = var.aws_region
}

module "feature_store" {
  source      = "../../modules/feature_store"
  project     = var.project
  environment = var.environment
  bucket_name = module.storage.bucket_name
  role_arn    = module.iam.data_engineer_role_arn
}