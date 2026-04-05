# local-claude

로컬 LLM 기반 Claude Code 클론. Apple Silicon + MLX 최적화.

## 아키텍처

**참고 프로젝트:**
- [tanbiralam/claude-code](https://github.com/tanbiralam/claude-code) -- TypeScript, React/Ink TUI, QueryEngine 패턴
- [ultraworkers/claw-code](https://github.com/ultraworkers/claw-code) -- Rust, ConversationRuntime, Hook 시스템, JSONL 세션

**적용한 패턴:**
- claw-code: 턴 기반 ConversationRuntime, JSONL 세션 저장, Hook 시스템
- claude-code: ToolRegistry 패턴, Slash Command 구조
- 양쪽: Permission 모델 (read-only / workspace-write / full-access)

## 구조

```
local-claude/
├── core/
│   ├── types.py          # Message, ToolCall, StreamEvent, Permission 등
│   ├── engine.py         # MLX LM Server API 래퍼 (스트리밍 + 동기)
│   ├── runtime.py        # ConversationRuntime (에이전트 루프)
│   ├── session.py        # JSONL 세션 관리
│   ├── hooks.py          # Pre/Post tool use hook 시스템
│   ├── tool_registry.py  # 도구 등록/실행 레지스트리
│   └── cli.py            # TUI (rich + prompt_toolkit)
├── skills/
│   ├── file_ops.py       # read_file, write_file, edit_file, list_files
│   ├── bash_exec.py      # bash 명령 실행
│   ├── search.py         # grep, glob 검색
│   └── web_fetch.py      # URL 내용 가져오기
├── commands/
│   ├── __init__.py       # CommandRegistry
│   └── builtins.py       # /help, /status, /compact, /tools, /sessions ...
├── sessions/             # JSONL 대화 저장
├── verify_model.py       # MLX 모델 검증
├── __main__.py           # 엔트리포인트
└── requirements.txt
```

## 요구사항

- Python 3.11+
- Apple Silicon Mac (M1/M2/M3/M4)
- 16GB+ RAM (27B-4bit 모델 기준 ~14GB VRAM)

## 설치 및 실행

```bash
# 1. Python 의존성
pip install -r requirements.txt
pip install mlx-lm

# 2. MLX 서버 시작
mlx_lm.server --model mlx-community/Qwen3.5-27B-4bit --port 8080

# 3. 모델 검증
python verify_model.py

# 4. CLI 실행
python __main__.py

# 옵션
python __main__.py -p "파이보나치 함수 만들어줘"          # 원샷 모드
python __main__.py -w /path/to/project                    # 워크스페이스 지정
python __main__.py --permission read-only                 # 읽기 전용 모드
python __main__.py --temperature 0.3 --max-tokens 8192    # 파라미터 조정
```

## 모델 옵션

| 모델 | 크기 | 권장 RAM |
|------|------|---------|
| Qwen3.5-27B-4bit | ~14GB | 36GB (권장) |
| Qwen3.5-27B-3bit | ~11GB | 16GB |

## Slash Commands

| 명령 | 설명 |
|------|------|
| `/help` | 명령어 목록 |
| `/status` | 세션 상태, 토큰 사용량 |
| `/compact [N]` | 오래된 메시지 압축 (최근 N개 유지) |
| `/tools` | 사용 가능한 도구 목록 |
| `/sessions` | 저장된 세션 목록 |
| `/resume <id>` | 세션 복원 |
| `/model` | 현재 모델 정보 |
| `/clear` | 대화 초기화 |
| `/exit` | 종료 |

## 도구 (Skills)

| 도구 | 권한 | 설명 |
|------|------|------|
| `read_file` | read-only | 파일 읽기 (라인 번호 포함) |
| `list_files` | read-only | 디렉토리 목록 |
| `grep` | read-only | 정규식 파일 내용 검색 |
| `glob` | read-only | 파일명 패턴 검색 |
| `write_file` | workspace-write | 파일 생성/덮어쓰기 |
| `edit_file` | workspace-write | 파일 부분 수정 |
| `bash` | full-access | 셸 명령 실행 |
| `web_fetch` | full-access | URL 내용 가져오기 |

## 위키 시스템

| 명령 | 설명 |
|------|------|
| `/ingest` | 프로젝트 파일 위키로 인제스트 |
| `/query` | 위키 자연어 검색 |
| `/wiki-search` | 위키 키워드 검색 |
| `/lint` | 위키 일관성 검사 |
| `/wiki-status` | 위키 상태 확인 |
| `/wiki-history` | 위키 변경 이력 |
| `/wiki-export` | 위키 마크다운 내보내기 |
