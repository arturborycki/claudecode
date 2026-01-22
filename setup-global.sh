#!/bin/bash

# Claude Code Global Setup Script
# Usage: ./setup-global.sh
# Installs global Claude Code configuration to ~/.claude/

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory (where templates are)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/global/.claude"
TARGET_DIR="$HOME/.claude"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Claude Code Global Setup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if template directory exists
if [ ! -d "$TEMPLATE_DIR" ]; then
    echo -e "${RED}Error: Template directory not found at $TEMPLATE_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}Source:${NC} $TEMPLATE_DIR"
echo -e "${GREEN}Target:${NC} $TARGET_DIR"
echo ""

# Function to copy file with backup
copy_file() {
    local src="$1"
    local dest="$2"
    local name="$3"

    if [ -f "$dest" ]; then
        echo -e "  ${YELLOW}[exists]${NC} $name"
        echo -e "           Backup? Overwrite? Skip? (b/o/s)"
        read -r choice
        case "$choice" in
            b|B)
                cp "$dest" "$dest.backup.$(date +%Y%m%d%H%M%S)"
                cp "$src" "$dest"
                echo -e "           ${GREEN}Backed up and replaced${NC}"
                ;;
            o|O)
                cp "$src" "$dest"
                echo -e "           ${GREEN}Overwritten${NC}"
                ;;
            *)
                echo -e "           ${YELLOW}Skipped${NC}"
                ;;
        esac
        return 0
    fi

    if [ -f "$src" ]; then
        # Ensure parent directory exists
        mkdir -p "$(dirname "$dest")"
        cp "$src" "$dest"
        echo -e "  ${GREEN}[done]${NC} $name"
    else
        echo -e "  ${RED}[miss]${NC} $name (template not found)"
    fi
}

# Copy root files
echo -e "${BLUE}Copying global files...${NC}"
copy_file "$TEMPLATE_DIR/MEMORY.md" "$TARGET_DIR/MEMORY.md" "MEMORY.md"
copy_file "$TEMPLATE_DIR/INFRASTRUCTURE.md" "$TARGET_DIR/INFRASTRUCTURE.md" "INFRASTRUCTURE.md"

# Ask about settings.json (might overwrite existing permissions)
echo ""
echo -e "${YELLOW}Copy settings.json? This contains permission rules.${NC}"
echo -e "${YELLOW}If you have existing settings, consider merging manually. (y/n)${NC}"
read -r copy_settings
if [[ "$copy_settings" =~ ^[Yy]$ ]]; then
    copy_file "$TEMPLATE_DIR/settings.json" "$TARGET_DIR/settings.json" "settings.json"
fi

# Create and copy commands
echo ""
echo -e "${BLUE}Setting up commands...${NC}"
mkdir -p "$TARGET_DIR/commands"

for cmd_file in "$TEMPLATE_DIR/commands"/*.md; do
    if [ -f "$cmd_file" ]; then
        filename=$(basename "$cmd_file")
        copy_file "$cmd_file" "$TARGET_DIR/commands/$filename" "commands/$filename"
    fi
done

# Create and copy rules
echo ""
echo -e "${BLUE}Setting up rules...${NC}"
mkdir -p "$TARGET_DIR/rules"

if [ -d "$TEMPLATE_DIR/rules" ]; then
    for rule_file in "$TEMPLATE_DIR/rules"/*.md; do
        if [ -f "$rule_file" ]; then
            filename=$(basename "$rule_file")
            copy_file "$rule_file" "$TARGET_DIR/rules/$filename" "rules/$filename"
        fi
    done
fi

# Summary
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Global setup complete!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Installed to:${NC} $TARGET_DIR"
echo ""
echo -e "${YELLOW}Available commands:${NC}"
echo "  /wrap      — End session, commit, document"
echo "  /sup       — Quick status check"
echo "  /fragile   — Review danger zones"
echo "  /plan      — Two-phase planning"
echo "  /research  — Deep exploration"
echo "  /infra     — Infrastructure reference"
echo "  /new-project — Set up new project"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Edit ~/.claude/MEMORY.md with your coding standards"
echo "  2. Edit ~/.claude/INFRASTRUCTURE.md with your servers"
echo "  3. Review ~/.claude/settings.json permissions"
echo ""
