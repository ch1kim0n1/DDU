package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type galleryDLAdapter struct {
	path string
}

func newGalleryDLAdapter() *galleryDLAdapter {
	path := strings.TrimSpace(os.Getenv("GALLERY_DL_PATH"))
	if path == "" {
		path = "gallery-dl"
	}
	return &galleryDLAdapter{path: path}
}

func (a *galleryDLAdapter) Download(ctx context.Context, destDir, url string, options map[string]string) ([]DownloadedFile, error) {
	if strings.TrimSpace(os.Getenv("MODEL_MODE")) == "stub" {
		return stubDownload(destDir, url), nil
	}
	args := []string{"--directory", destDir, "--no-download"}
	if len(options) > 0 {
		for key, value := range options {
			args = append(args, "--option", key+"="+value)
		}
	}
	args = append(args, url)
	cmd := exec.CommandContext(ctx, a.path, args...)
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("gallery-dl execution failed: %w", err)
	}
	return scanDownloadedFiles(destDir, url)
}

func scanDownloadedFiles(destDir, url string) ([]DownloadedFile, error) {
	var files []DownloadedFile
	err := filepath.Walk(destDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		files = append(files, DownloadedFile{
			Path:     path,
			Filename: filepath.Base(path),
			MimeType: guessMimeType(path),
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return files, nil
}

func stubDownload(destDir, url string) []DownloadedFile {
	stubPath := filepath.Join(destDir, "stub-image.jpg")
	_ = os.WriteFile(stubPath, []byte{0xff, 0xd8, 0xff, 0xd9}, 0o644)
	return []DownloadedFile{
		{Path: stubPath, Filename: "stub-image.jpg", MimeType: "image/jpeg"},
	}
}

func guessMimeType(path string) string {
	ext := strings.ToLower(filepath.Ext(path))
	switch ext {
	case ".jpg", ".jpeg":
		return "image/jpeg"
	case ".png":
		return "image/png"
	case ".gif":
		return "image/gif"
	case ".webp":
		return "image/webp"
	case ".mp4":
		return "video/mp4"
	case ".webm":
		return "video/webm"
	case ".json":
		return "application/json"
	case ".html", ".htm":
		return "text/html"
	default:
		return "application/octet-stream"
	}
}
