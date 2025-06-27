from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from uuid import uuid4
from enum import Enum


# -- Models --

class PlayerSymbol(str, Enum):
    X = "X"
    O_ = "O"  # Rename to avoid ambiguity (E741)


class MoveModel(BaseModel):
    row: int = Field(..., ge=0, le=2, description="Row index (0-2)")
    col: int = Field(..., ge=0, le=2, description="Column index (0-2)")
    player_id: str = Field(..., description="ID of the player making the move")


class PlayerModel(BaseModel):
    id: str = Field(..., description="Player unique identifier")
    symbol: PlayerSymbol = Field(..., description="X or O")
    name: Optional[str] = Field(
        None, description="Optional player name"
    )


class GameStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WIN = "win"
    DRAW = "draw"


class GameModel(BaseModel):
    id: str = Field(..., description="Game unique identifier")
    board: List[List[Optional[PlayerSymbol]]] = Field(
        ..., description="3x3 game board, each cell is X, O, or None"
    )
    players: List[PlayerModel] = Field(
        ..., description="List of players (max 2)"
    )
    status: GameStatus = Field(..., description="Current game state")
    winner_id: Optional[str] = Field(
        None, description="ID of the winner, if any"
    )
    turn: Optional[str] = Field(
        None, description="player_id whose turn it is"
    )


# -- In-Memory Game Store (for MVP, suitable for expansion) --
games: Dict[str, GameModel] = {}

# -- App and CORS config --
app = FastAPI(
    title="Tic Tac Toe Backend API",
    description="Handles Tic Tac Toe game management, moves, and state.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Helper Functions ---

# PUBLIC_INTERFACE
def create_new_game(player_name: Optional[str] = None) -> GameModel:
    """PUBLIC_INTERFACE: Create a new game with a single player as X."""

    player_id = str(uuid4())
    player = PlayerModel(id=player_id, symbol=PlayerSymbol.X, name=player_name)
    game_id = str(uuid4())
    board = [[None for _ in range(3)] for _ in range(3)]
    game = GameModel(
        id=game_id,
        board=board,
        players=[player],
        status=GameStatus.WAITING,
        winner_id=None,
        turn=player_id,
    )
    games[game_id] = game
    return game


# PUBLIC_INTERFACE
def join_game(game_id: str, player_name: Optional[str] = None) -> GameModel:
    """PUBLIC_INTERFACE: Join an existing game as O if there's space and not already started."""
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    game = games[game_id]
    if len(game.players) >= 2:
        raise HTTPException(status_code=400, detail="Game is already full")
    player_id = str(uuid4())
    new_player = PlayerModel(id=player_id, symbol=PlayerSymbol.O_, name=player_name)
    game.players.append(new_player)
    game.status = GameStatus.IN_PROGRESS
    # The player who created always starts (X)
    games[game_id] = game
    return game


# PUBLIC_INTERFACE
def get_game(game_id: str) -> GameModel:
    """PUBLIC_INTERFACE: Retrieve game by ID."""
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    return games[game_id]


def check_winner(board: List[List[Optional[PlayerSymbol]]]) -> Optional[PlayerSymbol]:
    """Check board for a win; returns symbol if found, else None."""
    lines = []

    # Rows and columns
    for i in range(3):
        lines.append(board[i])  # rows
        lines.append([board[0][i], board[1][i], board[2][i]])  # cols

    # Diagonals
    lines.append([board[0][0], board[1][1], board[2][2]])
    lines.append([board[0][2], board[1][1], board[2][0]])

    for line in lines:
        if line[0] and all(cell == line[0] for cell in line):
            return line[0]
    return None


def is_draw(board: List[List[Optional[PlayerSymbol]]]) -> bool:
    return all(cell is not None for row in board for cell in row)


# PUBLIC_INTERFACE
def make_move(game_id: str, move: MoveModel) -> GameModel:
    """PUBLIC_INTERFACE: Validate and apply move to game, update state, check win/draw."""
    if game_id not in games:
        raise HTTPException(status_code=404, detail="Game not found")
    game = games[game_id]

    if game.status not in [GameStatus.IN_PROGRESS]:
        raise HTTPException(status_code=400, detail="Game not in progress")

    # Player must be in this game and it must be their turn
    player = next((pl for pl in game.players if pl.id == move.player_id), None)
    if not player:
        raise HTTPException(status_code=403, detail="Player not in game")
    if game.turn != player.id:
        raise HTTPException(status_code=403, detail="Not this player's turn")

    r, c = move.row, move.col
    if game.board[r][c] is not None:
        raise HTTPException(status_code=400, detail="Cell already taken")

    game.board[r][c] = player.symbol

    # Check for winner
    winner_symbol = check_winner(game.board)
    if winner_symbol:
        game.status = GameStatus.WIN
        winner = next((pl for pl in game.players if pl.symbol == winner_symbol), None)
        if winner:
            game.winner_id = winner.id
        games[game_id] = game
        return game

    # Check for draw
    if is_draw(game.board):
        game.status = GameStatus.DRAW
        games[game_id] = game
        return game

    # Otherwise, switch turn: X->O, O->X
    next_player = next((pl for pl in game.players if pl.symbol != player.symbol), None)
    if not next_player:
        raise HTTPException(status_code=400, detail="Next player not found")
    game.turn = next_player.id
    games[game_id] = game
    return game


# ---- API Endpoints ----

@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint."""
    return {"message": "Healthy"}


@app.post(
    "/games",
    response_model=GameModel,
    tags=["Game"],
    summary="Create a new game",
)
def api_create_game(player_name: Optional[str] = None):
    """Create a new tic-tac-toe game as the first player."""
    return create_new_game(player_name=player_name)


@app.post(
    "/games/{game_id}/join",
    response_model=GameModel,
    tags=["Game"],
    summary="Join an existing game",
)
def api_join_game(game_id: str, player_name: Optional[str] = None):
    """Join an existing game as the second player (O)."""
    return join_game(game_id, player_name=player_name)


@app.get(
    "/games/{game_id}",
    response_model=GameModel,
    tags=["Game"],
    summary="Get game state",
)
def api_get_game(game_id: str):
    """Get the state of a game by ID."""
    return get_game(game_id)


@app.post(
    "/games/{game_id}/move",
    response_model=GameModel,
    tags=["Game"],
    summary="Make a move in the game",
)
def api_make_move(game_id: str, move: MoveModel):
    """Make a move (row, col) in a specified game."""
    return make_move(game_id, move)
