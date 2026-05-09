chcp 65001 >nul
@echo off
echo 🔍 Validando projeto antes do deploy...

:: 1. Verifica se está na pasta certa
if not exist ".git" (
    echo ❌ Erro: Não é um repositório Git. Execute na pasta raiz do projeto.
    exit /b 1
)

:: 2. Valida sintaxe Python
echo ✅ Verificando sintaxe...
python -m py_compile src\bot.py src\db.py
if errorlevel 1 (
    echo ❌ Erro de sintaxe detectado. Corrija antes de dar push.
    exit /b 1
)

:: 3. Verifica status do Git
echo 🔍 Verificando status do Git...
git status --short

:: 4. Verifica se .env existe (e avisa se estiver exposto)
if exist ".env" (
    findstr /C:".env" .gitignore >nul 2>&1
    if errorlevel 1 (
        echo ⚠️ ALERTA: .env existe mas não está no .gitignore!
        echo    Risco de expor senhas no GitHub.
    ) else (
        echo ✅ .env protegido no .gitignore
    )
)

:: 5. Lista arquivos modificados
echo.
echo 📋 Arquivos modificados:
git diff --name-only

echo.
echo ✅ Validação concluída! Pronto para commit/push.
echo.
pause