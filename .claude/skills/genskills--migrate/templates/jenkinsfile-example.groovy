// Jenkinsfile
pipeline {
  agent { docker { image 'node:20' } }
  stages {
    stage('Install') { steps { sh 'npm ci' } }
    stage('Test')    { steps { sh 'npm test' } }
    stage('Build')   { steps { sh 'npm run build' } }
    stage('Deploy')  {
      when { branch 'main' }
      steps { sh './deploy.sh' }
    }
  }
  post { always { junit 'reports/**/*.xml' } }
}
