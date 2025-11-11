# Contributing to Deduparr

Thank you for your interest in contributing to Deduparr! 🎉

## Code of Conduct

Be respectful and constructive. We're all here to build something great together.

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 20+
- Docker (optional, for testing)

### Development Setup

1. **Fork and clone the repository**

```bash
git clone https://github.com/YOUR_USERNAME/deduparr.git
cd deduparr
```

2. **Backend Setup**

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. **Frontend Setup**

```bash
cd frontend
npm install  # Uses package-lock.json for integrity verification
npm run audit  # (Optional) Check for security vulnerabilities locally
```

**Security Note**: We recommend using `package-lock.json` for package integrity. Supply chain protection is not enforced by CI/CD. See [docs/SECURITY.md](docs/SECURITY.md) for details.

4. **Run Development Servers**

Terminal 1 (Backend):
```bash
cd backend
source venv/bin/activate
python -m app.main
# API runs on http://localhost:3001
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
# UI runs on http://localhost:3000
```

## Development Workflow

### Branching Strategy

- `main` - Stable production code (all PRs merge here)
- `feature/your-feature-name` - Feature branches
- `fix/bug-description` - Bug fix branches

### Making Changes

1. Create a new branch from `main`

```bash
git checkout main
git pull origin main
git checkout -b feature/awesome-feature
```

2. Make your changes and commit

```bash
git add .
git commit -m "feat: add awesome feature"
```

3. Push and create a pull request to `main`

```bash
git push origin feature/awesome-feature
```

### Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Examples:
- `feat: add duplicate detection scoring system`
- `fix: resolve qBittorrent connection timeout`
- `docs: update installation instructions`

## Project Structure

```
deduparr/
├── backend/          # Python FastAPI backend
│   ├── app/
│   │   ├── api/      # API endpoints (routes/)
│   │   ├── core/     # Config, database
│   │   ├── models/   # Database models
│   │   ├── services/ # Business logic
│   │   └── main.py   # FastAPI app entry point
│   └── tests/        # Backend tests
├── frontend/         # React TypeScript frontend
│   └── src/
│       ├── components/  # UI components
│       ├── pages/       # Page components
│       ├── services/    # API client
│       └── types/       # TypeScript types
├── docs/             # User documentation
├── todo/             # Implementation plans and dev notes
├── config/           # Configuration examples
└── data/             # Runtime data (SQLite DB, encryption keys)
```

## Code Standards

### TypeScript/React Rules (React 19.2)

**FORBIDDEN:**
- ❌ `any` type - **NEVER use `any`**
- ❌ `useEffect` - Use React Query, form actions, or event handlers
- ❌ `useCallback` - Avoid premature optimization
- ❌ `Record<string, any>` - Use specific types like `Record<string, string>`

**REQUIRED:**
- ✅ Specific types: `string`, `number`, `ChangeEvent<HTMLInputElement>`
- ✅ React Query for data fetching
- ✅ `useTransition` for async operations
- ✅ Proper error boundaries

**Examples:**

```typescript
// ❌ WRONG - uses any
const handleChange = (e: any) => setValue(e.target.value)
const data: Record<string, any> = {}

// ✅ CORRECT - specific types
const handleChange = (e: ChangeEvent<HTMLInputElement>) => setValue(e.target.value)
const data: Record<string, string> = {}
```

### Python Rules

- Use **Black** for formatting: `black .`
- Use **Ruff** for linting: `ruff check .`
- Type hints are required
- Follow PEP 8

### TypeScript (Frontend)

- Use **ESLint**: `npm run lint`
- Follow React best practices
- Use functional components with hooks

## Testing

### Backend Tests

```bash
cd backend
pytest
pytest --cov=app tests/  # With coverage
```

### Frontend Tests

```bash
cd frontend
npm test
```

## Pull Request Process

1. **Update documentation** if you're adding features
2. **Add tests** for new functionality
3. **Ensure all tests pass**
4. **Update CHANGELOG.md** (if applicable)
5. **Request review** from maintainers

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Tests added/updated and passing
- [ ] Documentation updated
- [ ] Commit messages follow convention
- [ ] Branch is up-to-date with `main`

## Feature Requests & Bug Reports

- Use [GitHub Issues](https://github.com/deduparr-dev/deduparr/issues)
- Search existing issues first
- Use issue templates when available
- Provide as much detail as possible

## Questions?

- [GitHub Discussions](https://github.com/deduparr-dev/deduparr/discussions) - Ask questions and get help

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to Deduparr! 🚀
