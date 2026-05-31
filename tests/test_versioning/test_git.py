import pytest
import subprocess
import argparse

from unittest.mock import patch, MagicMock
from versioning import GitInfo, assert_clean_workspace, track_dev_build


# ✅ Mock subprocess output for Git commands
@patch("subprocess.run")
def test_git_info(mock_subproc):
    """Test GitInfo.from_ws() with mocked Git responses."""

    # Create a mock return object with `.stdout.strip()`
    def mock_git_command(args, cwd, capture_output, text, check):
        mock = MagicMock()
        
        # Simulated outputs for each Git command
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            mock.stdout = "main\n"
        elif args == ["git", "rev-parse", "--short", "HEAD"]:
            mock.stdout = "abc123\n"
        elif args == ["git", "status", "--porcelain"]:
            mock.stdout = ""  # No changed files
        elif args == ["git", "describe", "--tags", "--abbrev=0"]:
            mock.stdout = "v1.2.3\n"
        elif args == ["git", "diff"]:
            mock.stdout = "patch content"
        return mock

    # Set side_effect for mock_subproc
    mock_subproc.side_effect = mock_git_command

    # Call the function being tested
    git_info = GitInfo.from_ws()

    # ✅ Assertions
    assert git_info.branch == "main"
    assert git_info.commit == "abc123"
    assert git_info.last_tag == "v1.2.3"
    assert git_info.patch_str == "patch content"
    assert git_info.dirty is False

# ✅ Mock case where no Git tags exist
@patch("subprocess.run")
def test_git_info_no_tags(mock_subproc):
    """Test GitInfo when no Git tags exist."""

    def mock_git_command(args, cwd, capture_output, text, check):
        mock = MagicMock()
        if args == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            mock.stdout = "main\n"
        elif args == ["git", "rev-parse", "--short", "HEAD"]:
            mock.stdout = "abc123\n"
        elif args == ["git", "status", "--porcelain"]:
            mock.stdout = " "
        elif args == ["git", "describe", "--tags", "--abbrev=0"]:
            raise subprocess.CalledProcessError(1, "git describe")  # Simulate no tags
        elif args == ["git", "diff"]:
            mock.stdout = "patch content"
        return mock

    mock_subproc.side_effect = mock_git_command

    git_info = GitInfo.from_ws()

    # ✅ Expect branch and commit, but last_tag should be None
    assert git_info.branch == "main"
    assert git_info.commit == "abc123"
    assert git_info.last_tag is None


@patch("versioning.GitInfo.from_ws")
def test_assert_clean_workspace_rejects_dirty_build(mock_from_ws):
    git_info = MagicMock()
    git_info.dirty = True
    mock_from_ws.return_value = git_info

    with pytest.raises(SystemExit):
        assert_clean_workspace(argparse.Namespace(allow_dirty=False))


@patch("versioning.GitInfo.from_ws")
def test_assert_clean_workspace_allows_dirty_build_with_flag(mock_from_ws):
    git_info = MagicMock()
    git_info.dirty = True
    mock_from_ws.return_value = git_info

    assert_clean_workspace(argparse.Namespace(allow_dirty=True))


@patch("versioning.GitInfo.from_ws")
def test_dirty_dev_build_is_not_stored(mock_from_ws, tmp_path):
    mock_from_ws.return_value = GitInfo(
        branch="feature",
        commit="abc123",
        last_tag="v1.2.3",
        status_str="M file.c",
    )

    tracked_build = track_dev_build(
        argparse.Namespace(
            variant="satellite1_firmware_fixed_delay",
            build_dir=tmp_path,
        )
    )

    assert str(tracked_build.version) == "v1.2.3-dev"
    assert tracked_build.track_path is None
    assert not (tmp_path / "dev_tracking").exists()
