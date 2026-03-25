// ---------------------------------------------------------------------------
// Jenkinsfile — Playwright Lambda Test Pipeline
// ---------------------------------------------------------------------------
// Triggered on every git commit via a webhook or SCM poll.
//
// Pipeline stages:
//   1. Checkout          — pull source from SCM
//   2. Build & Push      — build Docker image, push to ECR
//   3. Run Tests         — invoke parallel Lambda shards via orchestrator.py
//   4. Report Results    — query DynamoDB and display consolidated results
//   5. Gate              — fail the build if any tests failed
//
// AWS credentials are supplied via the Jenkins credentials store.
// Inject them as a binding so they are never echoed in console output.
// ---------------------------------------------------------------------------

pipeline {

    agent any  // Run on any available Jenkins agent with Docker + Python

    // -----------------------------------------------------------------------
    // Pipeline-wide configuration
    // -----------------------------------------------------------------------
    options {
        timeout(time: 30, unit: 'MINUTES')   // Hard cap on total run time
        disableConcurrentBuilds()            // One run at a time per branch
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    // -----------------------------------------------------------------------
    // Parameters — can be overridden at build time or left as defaults
    // -----------------------------------------------------------------------
    parameters {
        string(
            name:         'ECR_REPO',
            defaultValue: 'playwright-tests',
            description:  'ECR repository name'
        )
        string(
            name:         'LAMBDA_FUNCTION',
            defaultValue: 'playwright-test-runner',
            description:  'Lambda function name to invoke'
        )
        string(
            name:         'AWS_REGION',
            defaultValue: 'us-east-1',
            description:  'AWS region'
        )
        string(
            name:         'SHARDS',
            defaultValue: '4',
            description:  'Number of parallel Lambda shards'
        )
    }

    // -----------------------------------------------------------------------
    // Environment variables — available to all stages
    // -----------------------------------------------------------------------
    environment {
        // Derive a unique run ID from the build number and short commit SHA.
        // This ties every DynamoDB result row back to a specific Jenkins build.
        RUN_ID = "run-${env.BUILD_NUMBER}-${env.GIT_COMMIT?.take(7) ?: 'local'}"

        // Image tag: use the short commit SHA so every push is traceable.
        IMAGE_TAG = "${env.GIT_COMMIT?.take(7) ?: 'latest'}"

        // Python path so all scripts can import from the project root
        PYTHONPATH = "${env.WORKSPACE}"

        // Suppress Python output buffering so logs appear in real time
        PYTHONUNBUFFERED = '1'
    }

    // -----------------------------------------------------------------------
    // Stages
    // -----------------------------------------------------------------------
    stages {

        // -------------------------------------------------------------------
        stage('Checkout') {
        // -------------------------------------------------------------------
            steps {
                // Standard SCM checkout — Jenkins populates GIT_COMMIT etc.
                checkout scm

                script {
                    echo "=== Build Info ==="
                    echo "Run ID   : ${env.RUN_ID}"
                    echo "Branch   : ${env.GIT_BRANCH}"
                    echo "Commit   : ${env.GIT_COMMIT}"
                    echo "Image Tag: ${env.IMAGE_TAG}"
                }
            }
        }

        // -------------------------------------------------------------------
        stage('Install Dependencies') {
        // -------------------------------------------------------------------
        // Install Python deps on the agent. In a production setup this would
        // typically be baked into the agent image to save time.
        // -------------------------------------------------------------------
            steps {
                sh '''
                    python3 -m pip install --quiet --upgrade pip
                    python3 -m pip install --quiet -r requirements.txt
                '''
            }
        }

        // -------------------------------------------------------------------
        stage('Build & Push to ECR') {
        // -------------------------------------------------------------------
        // Authenticate with AWS, build the Docker image, push to ECR.
        // AWS credentials are injected from the Jenkins credentials store —
        // they are masked in console output and never written to disk.
        // -------------------------------------------------------------------
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'aws-ecr-credentials',
                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    sh """
                        python3 push_to_ecr.py \
                            --repo    ${params.ECR_REPO} \
                            --tag     ${env.IMAGE_TAG} \
                            --region  ${params.AWS_REGION}
                    """
                }
            }

            post {
                success { echo "Image pushed: ${params.ECR_REPO}:${env.IMAGE_TAG}" }
                failure { error "ECR push failed — aborting pipeline" }
            }
        }

        // -------------------------------------------------------------------
        stage('Run Tests — Parallel Lambda Shards') {
        // -------------------------------------------------------------------
        // Invoke orchestrator.py which fans out N Lambda invocations
        // concurrently. Each Lambda shard writes results to DynamoDB
        // keyed by RUN_ID. orchestrator.py exits non-zero if any tests fail.
        // -------------------------------------------------------------------
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'aws-ecr-credentials',
                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    // Capture the exit code manually so we can still run
                    // the reporting stage even when tests fail.
                    script {
                        def rc = sh(
                            script: """
                                python3 orchestrator.py \
                                    --function  ${params.LAMBDA_FUNCTION} \
                                    --shards    ${params.SHARDS} \
                                    --run-id    ${env.RUN_ID} \
                                    --region    ${params.AWS_REGION}
                            """,
                            returnStatus: true
                        )
                        // Store for the gate stage; don't fail here so
                        // the report stage always runs.
                        env.TESTS_EXIT_CODE = "${rc}"
                        echo "Orchestrator exited with code: ${rc}"
                    }
                }
            }
        }

        // -------------------------------------------------------------------
        stage('Report Results') {
        // -------------------------------------------------------------------
        // Query DynamoDB and print the full consolidated report regardless
        // of whether tests passed or failed.
        // -------------------------------------------------------------------
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'aws-ecr-credentials',
                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    sh """
                        python3 reporter.py \
                            --run-id  ${env.RUN_ID} \
                            --region  ${params.AWS_REGION}
                    """
                }
            }
        }

        // -------------------------------------------------------------------
        stage('Gate — Pass or Fail Build') {
        // -------------------------------------------------------------------
        // Now that reporting is done, honour the orchestrator exit code.
        // This stage is what blocks a PR merge if tests are red.
        // -------------------------------------------------------------------
            steps {
                script {
                    if (env.TESTS_EXIT_CODE != '0') {
                        error "One or more tests FAILED — marking build UNSTABLE. See report above."
                    } else {
                        echo "All tests passed."
                    }
                }
            }
        }
    }

    // -----------------------------------------------------------------------
    // Post-pipeline actions
    // -----------------------------------------------------------------------
    post {

        always {
            // Archive the orchestrator console output as a build artifact
            // so it can be downloaded and reviewed after the build expires.
            echo "Run ID for DynamoDB lookup: ${env.RUN_ID}"
        }

        failure {
            // Notify on failure — swap emailext for Slack plugin if preferred
            emailext(
                subject: "FAILED: Playwright Tests — Build #${env.BUILD_NUMBER} [${env.GIT_BRANCH}]",
                body: """
                    Build #${env.BUILD_NUMBER} failed.

                    Branch  : ${env.GIT_BRANCH}
                    Commit  : ${env.GIT_COMMIT}
                    Run ID  : ${env.RUN_ID}

                    Console : ${env.BUILD_URL}console

                    Query results:
                    aws dynamodb query --table-name playwright-test-results \\
                        --key-condition-expression 'run_id = :r' \\
                        --expression-attribute-values '{":r": {"S": "${env.RUN_ID}"}}'
                """,
                to: '${DEFAULT_RECIPIENTS}'
            )
        }

        success {
            echo "Pipeline complete. All tests passed."
        }

        cleanup {
            // Remove dangling Docker images from the agent to prevent
            // disk exhaustion on long-lived build nodes.
            sh "docker image prune -f || true"
        }
    }
}
