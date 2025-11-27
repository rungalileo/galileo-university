#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Galileo University Setup Script
# ==============================================================================
# This script automates the Python virtual environment setup for the
# galileo-university_shareable project.
# ==============================================================================

# Configuration Constants
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="${SCRIPT_DIR}"
readonly VENV_DIR="${PROJECT_ROOT}/.venv"
readonly REQUIREMENTS_FILE="${PROJECT_ROOT}/requirements.txt"
readonly ENV_TEMPLATE="${PROJECT_ROOT}/.env.template"
readonly ENV_FILE="${PROJECT_ROOT}/.env"
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=12

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# ==============================================================================
# Utility Functions
# ==============================================================================

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_section() {
    echo ""
    echo -e "${BLUE}==>${NC} $1"
}

# ==============================================================================
# Validation Functions
# ==============================================================================

check_python_version() {
    print_section "Checking Python version..."

    # Try python3 first, then python
    local python_cmd=""
    if command -v python3 &> /dev/null; then
        python_cmd="python3"
    elif command -v python &> /dev/null; then
        python_cmd="python"
    else
        print_error "Python is not installed or not in PATH"
        return 1
    fi

    # Get version
    local version_output=$($python_cmd --version 2>&1)
    local version=$(echo "$version_output" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

    if [[ -z "$version" ]]; then
        print_error "Could not determine Python version"
        return 1
    fi

    # Parse major and minor versions
    local major=$(echo "$version" | cut -d. -f1)
    local minor=$(echo "$version" | cut -d. -f2)

    print_info "Found Python $version"

    # Check if version meets requirements
    if [[ $major -lt $MIN_PYTHON_MAJOR ]] || \
       [[ $major -eq $MIN_PYTHON_MAJOR && $minor -lt $MIN_PYTHON_MINOR ]]; then
        print_error "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR or higher is required"
        print_error "Current version: $version"
        return 1
    fi

    print_success "Python version $version meets requirements (>= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR)"

    # Export for use in other functions
    export PYTHON_CMD="$python_cmd"
}

# ==============================================================================
# Setup Functions
# ==============================================================================

create_virtual_environment() {
    print_section "Setting up virtual environment..."

    if [[ -d "$VENV_DIR" ]]; then
        print_warning "Virtual environment already exists at: $VENV_DIR"
        print_info "Skipping creation (script is idempotent)"

        # Verify it's actually a valid venv
        if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
            print_error "Directory exists but is not a valid virtual environment"
            print_info "Please remove $VENV_DIR and run this script again"
            return 1
        fi

        print_success "Existing virtual environment verified"
    else
        print_info "Creating virtual environment in: $VENV_DIR"

        if ! $PYTHON_CMD -m venv "$VENV_DIR"; then
            print_error "Failed to create virtual environment"
            return 1
        fi

        print_success "Virtual environment created successfully"
    fi
}

setup_env_file() {
    print_section "Setting up environment configuration..."

    # Check if template exists
    if [[ ! -f "$ENV_TEMPLATE" ]]; then
        print_error "Environment template not found: $ENV_TEMPLATE"
        return 1
    fi

    # Check if .env already exists
    if [[ -f "$ENV_FILE" ]]; then
        print_warning ".env file already exists"
        print_info "Skipping copy to preserve existing configuration"
        print_info "If you need a fresh copy, remove .env and run again"
        return 0
    fi

    # Copy template to .env
    if cp "$ENV_TEMPLATE" "$ENV_FILE"; then
        print_success "Created .env file from template"
    else
        print_error "Failed to copy .env.template to .env"
        return 1
    fi
}

install_dependencies() {
    print_section "Installing dependencies..."

    # Verify requirements.txt exists
    if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
        print_error "Requirements file not found: $REQUIREMENTS_FILE"
        return 1
    fi

    # Activate virtual environment temporarily for this function
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    # Upgrade pip first
    print_info "Upgrading pip..."
    if ! pip install --upgrade pip --quiet; then
        print_error "Failed to upgrade pip"
        deactivate
        return 1
    fi

    # Install dependencies
    print_info "Installing packages from requirements.txt..."
    print_info "This may take a few minutes..."

    if pip install -r "$REQUIREMENTS_FILE" --quiet; then
        print_success "All dependencies installed successfully"
    else
        print_error "Failed to install dependencies"
        deactivate
        return 1
    fi

    deactivate
}

verify_imports() {
    print_section "Verifying key imports..."

    # Activate virtual environment
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"

    local failed=0

    # Test galileo import
    print_info "Testing galileo import..."
    if $PYTHON_CMD -c "import galileo" 2>/dev/null; then
        print_success "galileo imports successfully"
    else
        print_error "Failed to import galileo"
        failed=1
    fi

    # Test langchain import
    print_info "Testing langchain import..."
    if $PYTHON_CMD -c "import langchain" 2>/dev/null; then
        print_success "langchain imports successfully"
    else
        print_error "Failed to import langchain"
        failed=1
    fi

    # Test other critical imports
    local packages=("pandas" "dotenv" "langchain_openai" "langgraph")
    for pkg in "${packages[@]}"; do
        if $PYTHON_CMD -c "import ${pkg//-/_}" 2>/dev/null; then
            print_success "${pkg} imports successfully"
        else
            print_warning "Package ${pkg} import check failed"
        fi
    done

    deactivate

    if [[ $failed -eq 1 ]]; then
        return 1
    fi
}

# ==============================================================================
# Main Function
# ==============================================================================

main() {
    # Display banner
    echo ""
    echo "========================================"
    echo "  Galileo University Setup Script"
    echo "========================================"
    echo ""

    # Run all setup steps
    check_python_version || exit 1
    create_virtual_environment || exit 1
    setup_env_file || exit 1
    install_dependencies || exit 1
    verify_imports || exit 1

    # Success summary
    echo ""
    echo "========================================"
    print_success "Setup completed successfully!"
    echo "========================================"
    echo ""

    # Instructions for user
    print_section "Next Steps:"
    echo ""
    echo "1. Activate the virtual environment:"
    echo ""
    echo "   source .venv/bin/activate"
    echo ""
    echo "2. Edit the .env file with your Galileo credentials:"
    echo ""
    echo "   Required variables:"
    echo "   - GALILEO_API_KEY"
    echo "   - GALILEO_CONSOLE_URL"
    echo "   - GALILEO_PROJECT"
    echo ""
    echo "3. Run the getting started scripts:"
    echo ""
    echo "   python getting_started/rag/step1_get_started.py"
    echo ""

    exit 0
}

# Run main function
main "$@"
