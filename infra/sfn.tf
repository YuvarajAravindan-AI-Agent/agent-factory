resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${var.name}-pipeline"
  retention_in_days = 30
}

resource "aws_iam_role" "sfn" {
  name = "${var.name}-pipeline"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.acct } }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = [aws_lambda_function.tasks.arn, "${aws_lambda_function.tasks.arn}:*"] },
      { Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"],
      Resource = [aws_codebuild_project.deps.arn, aws_codebuild_project.test.arn] },
      # .sync integrations use a managed EventBridge rule to learn when the build finishes.
      { Effect = "Allow", Action = ["events:PutTargets", "events:PutRule", "events:DescribeRule"],
      Resource = "arn:${data.aws_partition.p.partition}:events:${var.region}:${local.acct}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule" },
      { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"],
      Resource = "*" },
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.name}-pipeline"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/pipeline.asl.json", {
    tasks_fn = aws_lambda_function.tasks.arn
    bucket   = aws_s3_bucket.ws.bucket
    deps     = aws_codebuild_project.deps.name
    test     = aws_codebuild_project.test.name
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
  depends_on = [aws_iam_role_policy.sfn]
}

output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
output "approval_url" { value = aws_lambda_function_url.approve.function_url }
