"""
Tests for disk scan service
"""

import os
import tempfile
from pathlib import Path

import pytest

from app.services.disk_scan_service import (
    DiskScanService,
    is_sample_file,
)


class TestIsSampleFile:
    """Tests for sample file detection"""

    def test_sample_in_filename(self):
        assert is_sample_file("/movies/Movie.2023.sample.mkv") is True
        assert is_sample_file("/movies/Movie.2023.SAMPLE.mkv") is True
        assert is_sample_file("/movies/Movie.2023.Sample.mkv") is True

    def test_sample_in_directory(self):
        assert is_sample_file("/movies/Sample/Movie.2023.mkv") is True
        assert is_sample_file("/movies/SAMPLE/Movie.2023.mkv") is True
        assert is_sample_file("/movies/sample/Movie.2023.mkv") is True

    def test_trailer_file(self):
        assert is_sample_file("/movies/Movie.2023.trailer.mkv") is True
        assert is_sample_file("/movies/Movie.2023.Trailer.mkv") is True

    def test_preview_file(self):
        assert is_sample_file("/movies/Movie.2023.preview.mkv") is True

    def test_rarbg_file(self):
        assert is_sample_file("/movies/rarbg.com.Movie.2023.mkv") is True

    def test_sample_with_separators(self):
        assert is_sample_file("/movies/Movie.2023-sample.mkv") is True
        assert is_sample_file("/movies/Movie.2023_sample.mkv") is True
        assert is_sample_file("/movies/Movie.2023.sample.mkv") is True

    def test_normal_file(self):
        assert is_sample_file("/movies/Movie.2023.1080p.mkv") is False
        assert is_sample_file("/movies/Movie.2023.BluRay.mkv") is False

    def test_empty_path(self):
        assert is_sample_file("") is False
        assert is_sample_file(None) is False


class TestDiskScanService:
    """Tests for DiskScanService"""

    @pytest.fixture
    def service(self):
        return DiskScanService()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_is_video_file(self, service):
        """Test video file detection by extension"""
        assert service._is_video_file("/movies/movie.mkv") is True
        assert service._is_video_file("/movies/movie.mp4") is True
        assert service._is_video_file("/movies/movie.avi") is True
        assert service._is_video_file("/movies/movie.mov") is True
        assert service._is_video_file("/movies/movie.wmv") is True
        assert service._is_video_file("/movies/movie.flv") is True
        assert service._is_video_file("/movies/movie.webm") is True
        assert service._is_video_file("/movies/movie.m4v") is True
        assert service._is_video_file("/movies/movie.mpg") is True
        assert service._is_video_file("/movies/movie.mpeg") is True
        assert service._is_video_file("/movies/movie.m2ts") is True
        assert service._is_video_file("/movies/movie.ts") is True

        assert service._is_video_file("/movies/movie.MKV") is True
        assert service._is_video_file("/movies/movie.MP4") is True

        assert service._is_video_file("/movies/movie.txt") is False
        assert service._is_video_file("/movies/movie.jpg") is False
        assert service._is_video_file("/movies/movie.nfo") is False

    def test_normalize_filename_basic(self, service):
        """Test basic filename normalization"""
        assert service._normalize_filename("Movie.Name.2023.mkv") == "movie name 2023"
        assert service._normalize_filename("Movie_Name_2023.mp4") == "movie name 2023"
        assert service._normalize_filename("Movie-Name-2023.avi") == "movie name 2023"

    def test_normalize_filename_quality_markers(self, service):
        """Test removal of quality markers"""
        assert (
            service._normalize_filename("Movie.2023.1080p.BluRay.x264.mkv")
            == "movie 2023"
        )
        assert (
            service._normalize_filename("Movie.2023.2160p.WEB-DL.H265.mkv")
            == "movie 2023"
        )
        assert (
            service._normalize_filename("Movie.2023.720p.HDTV.x264.mkv") == "movie 2023"
        )
        assert (
            service._normalize_filename("Movie.2023.4K.UHD.BluRay.mkv") == "movie 2023"
        )

    def test_normalize_filename_audio_codecs(self, service):
        """Test removal of audio codec markers"""
        # 7.1 is now correctly removed as a quality marker
        assert (
            service._normalize_filename("Movie.2023.DTS-HD.MA.7.1.mkv") == "movie 2023"
        )
        assert (
            service._normalize_filename("Movie.2023.TrueHD.Atmos.mkv") == "movie 2023"
        )
        assert service._normalize_filename("Movie.2023.AAC.mkv") == "movie 2023"
        assert service._normalize_filename("Movie.2023.AC3.mkv") == "movie 2023"

    def test_normalize_filename_language_tags(self, service):
        """Test removal of language tags"""
        assert service._normalize_filename("Movie.2023.NORDiC.ENG.mkv") == "movie 2023"
        assert service._normalize_filename("Movie.2023.SWEDiSH.mkv") == "movie 2023"

    def test_normalize_filename_release_group(self, service):
        """Test removal of release group"""
        assert (
            service._normalize_filename("Movie.2023.1080p.BluRay.x264-GROUP")
            == "movie 2023"
        )
        assert service._normalize_filename("Movie.2023.WEB-DL-GROUP2") == "movie 2023"

    def test_normalize_filename_case_sensitivity(self, service):
        """Test case insensitivity"""
        name1 = service._normalize_filename("TestMovie.2015.SWEDiSH.2160p.mkv")
        name2 = service._normalize_filename("testmovie.2015.swedish.2160p.mkv")
        assert name1 == name2

    def test_extract_year(self, service):
        """Test year extraction"""
        assert service._extract_year("Movie.2023.1080p.mkv") == "2023"
        assert service._extract_year("Movie.1999.BluRay.mkv") == "1999"
        assert service._extract_year("Movie.2015.WEB-DL.mkv") == "2015"
        assert service._extract_year("Movie.mkv") is None
        assert service._extract_year("Movie.1899.mkv") is None
        assert service._extract_year("Movie.2100.mkv") is None

    def test_extract_episode_info_s01e01_format(self, service):
        """Test episode info extraction - S01E01 format"""
        assert service._extract_episode_info("Show.S01E01.1080p.mkv") == "S01E01"
        assert service._extract_episode_info("Show.s01e01.mkv") == "S01E01"
        assert service._extract_episode_info("Show.S1E1.mkv") == "S01E01"
        assert service._extract_episode_info("Show.s05e12.mkv") == "S05E12"

    def test_extract_episode_info_1x01_format(self, service):
        """Test episode info extraction - 1x01 format"""
        assert service._extract_episode_info("Show.1x01.1080p.mkv") == "S01E01"
        assert service._extract_episode_info("Show.5x12.mkv") == "S05E12"

    def test_extract_episode_info_season_episode_format(self, service):
        """Test episode info extraction - season.episode format"""
        assert service._extract_episode_info("Show.Season.1.Episode.1.mkv") == "S01E01"
        assert service._extract_episode_info("Show.season.5.episode.12.mkv") == "S05E12"

    def test_extract_episode_info_no_match(self, service):
        """Test episode info extraction with no match"""
        assert service._extract_episode_info("Movie.2023.mkv") is None
        assert service._extract_episode_info("Random.File.mkv") is None

    def test_are_hardlinks_same_inode(self, service, temp_dir):
        """Test hardlink detection - same inode"""
        file1 = os.path.join(temp_dir, "file1.mkv")
        file2 = os.path.join(temp_dir, "file2.mkv")

        Path(file1).touch()

        os.link(file1, file2)

        assert service._are_hardlinks(file1, file2) is True

    def test_are_hardlinks_different_inodes(self, service, temp_dir):
        """Test hardlink detection - different files"""
        file1 = os.path.join(temp_dir, "file1.mkv")
        file2 = os.path.join(temp_dir, "file2.mkv")

        Path(file1).touch()
        Path(file2).touch()

        assert service._are_hardlinks(file1, file2) is False

    def test_are_hardlinks_nonexistent_files(self, service):
        """Test hardlink detection with nonexistent files"""
        assert (
            service._are_hardlinks("/nonexistent/file1.mkv", "/nonexistent/file2.mkv")
            is False
        )

    def test_scan_directory_empty(self, service, temp_dir):
        """Test scanning an empty directory"""
        files = service._scan_directory(temp_dir)
        assert files == []

    def test_scan_directory_with_videos(self, service, temp_dir):
        """Test scanning directory with video files"""
        Path(os.path.join(temp_dir, "movie1.mkv")).touch()
        Path(os.path.join(temp_dir, "movie2.mp4")).touch()
        Path(os.path.join(temp_dir, "readme.txt")).touch()

        files = service._scan_directory(temp_dir, recursive=False)

        assert len(files) == 2
        assert any("movie1.mkv" in f for f in files)
        assert any("movie2.mp4" in f for f in files)
        assert not any("readme.txt" in f for f in files)

    def test_scan_directory_excludes_samples(self, service, temp_dir):
        """Test that sample files are excluded"""
        Path(os.path.join(temp_dir, "movie.mkv")).touch()
        Path(os.path.join(temp_dir, "movie.sample.mkv")).touch()

        files = service._scan_directory(temp_dir, recursive=False)

        assert len(files) == 1
        assert "movie.mkv" in files[0]
        assert "sample" not in files[0]

    def test_scan_directory_recursive(self, service, temp_dir):
        """Test recursive directory scanning"""
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        Path(os.path.join(temp_dir, "movie1.mkv")).touch()
        Path(os.path.join(subdir, "movie2.mkv")).touch()

        files = service._scan_directory(temp_dir, recursive=True)

        assert len(files) == 2

        files = service._scan_directory(temp_dir, recursive=False)

        assert len(files) == 1

    def test_group_by_normalized_name_movies(self, service, temp_dir):
        """Test grouping movie files by normalized name"""
        files = [
            "/movies/Movie.2023.1080p.BluRay.x264-GROUP1/movie.2023.mkv",
            "/movies/Movie.2023.720p.WEB-DL.x264-GROUP2/Movie.2023.mp4",
            "/movies/Other.Movie.2023.mkv",
        ]

        groups = service._group_by_normalized_name(files, is_movie=True)

        assert len(groups) == 1
        assert "movie 2023|2023" in groups
        assert len(groups["movie 2023|2023"]) == 2

    def test_group_by_normalized_name_episodes(self, service, temp_dir):
        """Test grouping episode files by show and episode"""
        files = [
            "/shows/Show.Name/Season.1/Show.Name.S01E01.1080p.mkv",
            "/shows/Show.Name/Season.1/Show.Name.s01e01.720p.mp4",
            "/shows/Show.Name/Season.1/Show.Name.S01E02.mkv",
        ]

        groups = service._group_by_normalized_name(files, is_movie=False)

        assert len(groups) == 1
        assert any("S01E01" in key for key in groups.keys())

        key = next(key for key in groups.keys() if "S01E01" in key)
        assert len(groups[key]) == 2

    def test_process_groups_removes_hardlinked_groups(self, service, temp_dir):
        """Test that hardlinked files in same group are filtered out"""
        # Create two hardlinks
        file1 = Path(temp_dir) / "movie1.mkv"
        file1.write_text("content")
        file2 = Path(temp_dir) / "movie1_hardlink.mkv"
        os.link(file1, file2)

        groups = {"movie": [str(file1), str(file2)]}
        result = service._process_groups(groups, check_size=False, check_checksum=False)

        assert len(result) == 0  # Group should be removed (all hardlinks)

    def test_process_groups_keeps_true_duplicates(self, service, temp_dir):
        """Test that true duplicates (different inodes) are kept"""
        file1 = Path(temp_dir) / "movie1.mkv"
        file1.write_text("content")
        file2 = Path(temp_dir) / "movie1_copy.mkv"
        file2.write_text("content")

        groups = {"movie": [str(file1), str(file2)]}
        result = service._process_groups(groups, check_size=False, check_checksum=False)

        assert len(result) == 1
        assert "movie" in result
        assert len(result["movie"]) == 2

    def test_process_groups_mixed_hardlinks_and_duplicates(self, service, temp_dir):
        """Test mixed scenario with hardlinks and true duplicates"""
        file1 = Path(temp_dir) / "movie1.mkv"
        file1.write_text("content")
        file2 = Path(temp_dir) / "movie1_hardlink.mkv"
        os.link(file1, file2)
        file3 = Path(temp_dir) / "movie1_copy.mkv"
        file3.write_text("content")

        groups = {"movie": [str(file1), str(file2), str(file3)]}
        result = service._process_groups(groups, check_size=False, check_checksum=False)

        # Should keep the original and the true copy, filtering out one hardlink
        assert len(result) == 1
        assert len(result["movie"]) == 2

    def test_filter_hardlinks_keeps_true_duplicates(self, service, temp_dir):
        """Test that true duplicates (different inodes) are kept"""
        file1 = os.path.join(temp_dir, "movie1.mkv")
        file2 = os.path.join(temp_dir, "movie2.mkv")

        Path(file1).touch()
        Path(file2).touch()

        groups = {"movie|2023": [file1, file2]}

        result = service._process_groups(groups, check_size=False, check_checksum=False)

        assert len(result) == 1
        assert "movie|2023" in result
        assert len(result["movie|2023"]) == 2

    def test_filter_hardlinks_mixed_hardlinks_and_duplicates(self, service, temp_dir):
        """Test filtering with mix of hardlinks and true duplicates"""
        file1 = os.path.join(temp_dir, "movie1.mkv")
        file2 = os.path.join(temp_dir, "movie2.mkv")
        file3 = os.path.join(temp_dir, "movie3.mkv")

        Path(file1).touch()
        os.link(file1, file2)
        Path(file3).touch()

        groups = {"movie|2023": [file1, file2, file3]}

        result = service._process_groups(groups, check_size=False, check_checksum=False)

        assert len(result) == 1
        assert len(result["movie|2023"]) == 2

    def test_find_duplicate_movies_empty_directory(self, service, temp_dir):
        """Test finding duplicates in empty directory"""
        result = service.find_duplicate_movies_on_disk([temp_dir])
        assert result == {}

    def test_find_duplicate_movies_no_duplicates(self, service, temp_dir):
        """Test finding duplicates when there are none"""
        Path(os.path.join(temp_dir, "Movie1.2023.mkv")).touch()
        Path(os.path.join(temp_dir, "Movie2.2024.mkv")).touch()

        result = service.find_duplicate_movies_on_disk([temp_dir])
        assert result == {}

    def test_find_duplicate_movies_with_duplicates(self, service, temp_dir):
        """Test finding actual duplicate movies"""
        subdir1 = os.path.join(temp_dir, "Movie.2023.1080p")
        subdir2 = os.path.join(temp_dir, "Movie.2023.720p")
        os.makedirs(subdir1)
        os.makedirs(subdir2)

        file1 = os.path.join(subdir1, "Movie.2023.1080p.BluRay.mkv")
        file2 = os.path.join(subdir2, "Movie.2023.720p.WEB-DL.mkv")

        Path(file1).touch()
        Path(file2).touch()

        result = service.find_duplicate_movies_on_disk([temp_dir])

        assert len(result) == 1
        assert "movie 2023|2023" in result
        assert len(result["movie 2023|2023"]) == 2

    def test_find_duplicate_movies_nonexistent_directory(self, service):
        """Test handling of nonexistent directories"""
        result = service.find_duplicate_movies_on_disk(["/nonexistent/directory"])
        assert result == {}

    def test_find_duplicate_episodes_with_duplicates(self, service, temp_dir):
        """Test finding duplicate episodes"""
        show_dir = os.path.join(temp_dir, "Show.Name")
        os.makedirs(show_dir)

        file1 = os.path.join(show_dir, "Show.Name.S01E01.1080p.mkv")
        file2 = os.path.join(show_dir, "Show.Name.s01e01.720p.mkv")

        Path(file1).touch()
        Path(file2).touch()

        result = service.find_duplicate_episodes_on_disk([temp_dir])

        assert len(result) == 1
        key = next(iter(result.keys()))
        assert "S01E01" in key
        assert len(result[key]) == 2

    def test_disk_file_info_structure(self, service, temp_dir):
        """Test that DiskFileInfo has correct structure"""
        file1 = os.path.join(temp_dir, "movie1.mkv")
        file2 = os.path.join(temp_dir, "movie2.mkv")

        Path(file1).write_text("test content 1")
        Path(file2).write_text("test content 2")

        groups = {"movie|2023": [file1, file2]}
        result = service._process_groups(groups, check_size=False, check_checksum=False)

        assert "movie|2023" in result
        file_info = result["movie|2023"][0]

        assert "path" in file_info
        assert "size" in file_info
        assert "is_hardlink" in file_info
        assert "inode" in file_info
        assert "normalized_name" in file_info

        assert isinstance(file_info["path"], str)
        assert isinstance(file_info["size"], int)
        assert isinstance(file_info["is_hardlink"], bool)
        assert isinstance(file_info["inode"], int)
        assert isinstance(file_info["normalized_name"], str)

    def test_case_sensitivity_different_directories(self, service, temp_dir):
        """Test that duplicates with different case are detected across directories"""
        dir1 = os.path.join(temp_dir, "Example.Movie.2015.SWEDiSH.2160p.WEB.h265-GROUP")
        dir2 = os.path.join(temp_dir, "Example Movie (2015)")
        os.makedirs(dir1)
        os.makedirs(dir2)

        file1 = os.path.join(
            dir1, "example.movie.2015.swedish.2160p.web.h265-group.mkv"
        )
        file2 = os.path.join(
            dir2, "Example.Movie.2015.SWEDiSH.2160p.WEB.h265-GROUP.mkv"
        )

        Path(file1).touch()
        Path(file2).touch()

        result = service.find_duplicate_movies_on_disk([temp_dir])

        assert len(result) == 1
        key = next(iter(result.keys()))
        assert "example" in key and "2015" in key
        assert len(result[key]) == 2

    def test_complex_quality_markers_removed(self, service, temp_dir):
        """Test that complex quality markers and audio codecs are properly removed"""
        dir1 = os.path.join(
            temp_dir,
            "Test.Film.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-GROUP",
        )
        dir2 = os.path.join(temp_dir, "Test Film 2 (2022)")
        os.makedirs(dir1)
        os.makedirs(dir2)

        file1 = os.path.join(
            dir1,
            "Test.Film.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-GROUP.mkv",
        )
        file2 = os.path.join(
            dir2,
            "Test.Film.2.2022.NORDiC.ENG.2160p.SDR.BluRay.DTS-HD.MA.TrueHD.7.1.Atmos.x265-GROUP.mkv",
        )

        Path(file1).touch()
        Path(file2).touch()

        result = service.find_duplicate_movies_on_disk([temp_dir])

        assert len(result) == 1
        key = next(iter(result.keys()))
        assert "test" in key and "2022" in key
        assert len(result[key]) == 2
