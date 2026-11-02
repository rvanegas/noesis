;;; noesis.el --- Minor mode for NOESIS conversation transcript files  -*- lexical-binding: t -*-

;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: convenience tools markdown

;;; Commentary:
;; Support for NOESIS-format markdown conversation files.  Adds syntax
;; highlighting for dates, section headers, reference lines, and edit
;; directives; commands to invoke the noesis CLI (reply, fix, check,
;; validate, new); and navigation between turns.
;;
;; Quickstart:
;;   (require 'noesis)
;;   (add-hook 'find-file-hook #'noesis-maybe-enable)
;;
;; With markdown-mode:
;;   (add-hook 'markdown-mode-hook #'noesis-maybe-enable)

;;; Code:

(require 'seq)

(defgroup noesis nil
  "Support for NOESIS conversation transcript files."
  :group 'tools
  :prefix "noesis-")

(defcustom noesis-executable "noesis"
  "Path to the noesis executable."
  :type 'string
  :group 'noesis)

(defcustom noesis-revert-after-modify t
  "Revert the buffer automatically after `noesis-reply' or `noesis-fix' succeeds."
  :type 'boolean
  :group 'noesis)

;; ── Faces ────────────────────────────────────────────────────────────────────

(defface noesis-date-face
  '((t :inherit font-lock-constant-face))
  "Face for the yyyy-mm-dd date line in an NOESIS preamble."
  :group 'noesis)

(defface noesis-speaker-face
  '((t :inherit font-lock-keyword-face :weight bold))
  "Face for the speaker name in an NOESIS section header (## Speaker)."
  :group 'noesis)

(defface noesis-reference-face
  '((t :inherit font-lock-string-face))
  "Face for NOESIS reference lines (| Author (year) *Title*)."
  :group 'noesis)

;; ── Font-lock ────────────────────────────────────────────────────────────────

(defconst noesis--font-lock-keywords
  '(;; Date line: yyyy-mm-dd standing alone on a line.
    ("^[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}$"
     . 'noesis-date-face)
    ;; Section headers: ## Speaker — highlight the speaker name.
    ("^##[[:space:]]+\\(.+\\)$"
     (1 'noesis-speaker-face))
    ;; Reference lines: | Author (year) *Title*
    ("^|[[:space:]].+$"
     . 'noesis-reference-face)
)
  "NOESIS-specific font-lock keywords.")

;; ── Keymap ───────────────────────────────────────────────────────────────────

(defvar noesis-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-r") #'noesis-reply)
    (define-key map (kbd "C-c C-f") #'noesis-fix)
    (define-key map (kbd "C-c C-k") #'noesis-check)
    (define-key map (kbd "C-c C-v") #'noesis-validate)
    (define-key map (kbd "C-c C-n") #'noesis-new)
    (define-key map (kbd "M-n")     #'noesis-next-turn)
    (define-key map (kbd "M-p")     #'noesis-prev-turn)
    (define-key map (kbd "C-c C-e") #'noesis-goto-input)
    map)
  "Keymap for `noesis-mode'.")

;; ── Internal helpers ─────────────────────────────────────────────────────────

(defun noesis--require-file ()
  "Signal an error if the current buffer has no associated file."
  (unless (buffer-file-name)
    (user-error "Buffer is not visiting a file")))

(defun noesis--output-buffer ()
  "Return the *noesis* output buffer, erased and ready."
  (let ((buf (get-buffer-create "*noesis*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t)) (erase-buffer)))
    buf))

(defun noesis--run-async (args &optional sentinel)
  "Start noesis with ARGS, streaming output to *noesis*.
Save the current buffer first.  SENTINEL, if given, is called with
\(process event) on exit.  Returns the process object."
  (noesis--require-file)
  (save-buffer)
  (let* ((file     (buffer-file-name))
         (dir      (file-name-directory file))
         (basename (file-name-nondirectory file))
         (buf      (noesis--output-buffer))
         (cmd      (cons noesis-executable (append args (list basename)))))
    (with-current-buffer buf
      (setq default-directory dir))
    (display-buffer buf)
    (let ((proc (apply #'start-process "noesis" buf cmd)))
      (when sentinel
        (set-process-sentinel proc sentinel))
      proc)))

(defun noesis--revert-sentinel (source-buf)
  "Return a process sentinel that reverts SOURCE-BUF on success."
  (lambda (proc _event)
    (when (and (zerop (process-exit-status proc))
               (buffer-live-p source-buf))
      (with-current-buffer source-buf
        (revert-buffer t t t)))))

;; ── Commands ─────────────────────────────────────────────────────────────────

(defun noesis--reply-sentinel (source-buf)
  "Return a sentinel that makes SOURCE-BUF writable again when noesis exits,
reverting it first on success (if `noesis-revert-after-modify')."
  (lambda (proc _event)
    (when (and (memq (process-status proc) '(exit signal))
               (buffer-live-p source-buf))
      (with-current-buffer source-buf
        (setq buffer-read-only nil)
        (when (and noesis-revert-after-modify (zerop (process-exit-status proc)))
          (revert-buffer t t t))))))

;;;###autoload
(defun noesis-reply ()
  "Run `noesis reply' on the current file and revert when done.
The buffer is read-only while the reply runs (on noesis's server, when the
library is mirrored there), so nothing typed meanwhile is lost to the revert."
  (interactive)
  (let ((source (current-buffer)))
    (noesis--run-async '("reply") (noesis--reply-sentinel source))
    (setq buffer-read-only t)))

;;;###autoload
(defun noesis-fix ()
  "Run `noesis fix' on the current file and revert when done."
  (interactive)
  (noesis--run-async
   '("fix")
   (when noesis-revert-after-modify
     (noesis--revert-sentinel (current-buffer)))))

;;;###autoload
(defun noesis-check ()
  "Run `noesis check' on the current file."
  (interactive)
  (noesis--run-async '("check")))

;;;###autoload
(defun noesis-validate ()
  "Run `noesis validate' on the current file."
  (interactive)
  (noesis--run-async '("validate")))

;;;###autoload
(defun noesis-new (title)
  "Create a new NOESIS transcript with TITLE in the current directory.
Opens the created file(s) for editing."
  (interactive "sNew transcript title: ")
  (let* ((dir (or (and (buffer-file-name)
                       (file-name-directory (buffer-file-name)))
                  default-directory))
         (created-files nil))
    (with-temp-buffer
      (let ((default-directory dir))
        (call-process noesis-executable nil t nil "new" title))
      (setq created-files
            (seq-filter (lambda (l) (string-suffix-p ".md" l))
                        (split-string (buffer-string) "\n" t))))
    (if (null created-files)
        (message "noesis new: no file created")
      (dolist (f (reverse created-files))
        (find-file (expand-file-name f dir))))))

;; ── Navigation ───────────────────────────────────────────────────────────────

;;;###autoload
(defun noesis-next-turn ()
  "Move point to the next `## Speaker' heading."
  (interactive)
  (let ((origin (point)))
    (end-of-line)
    (if (re-search-forward "^## " nil t)
        (beginning-of-line)
      (goto-char origin)
      (message "No more turns"))))

;;;###autoload
(defun noesis-prev-turn ()
  "Move point to the previous `## Speaker' heading."
  (interactive)
  (let ((origin (point)))
    (beginning-of-line)
    (if (re-search-backward "^## " nil t)
        (beginning-of-line)
      (goto-char origin)
      (message "No previous turn"))))

(defun noesis--ai-speaker-p (speaker)
  "Return non-nil if SPEAKER is a known AI assistant name."
  (member (downcase speaker) '("claude" "gpt")))

(defun noesis--turn-speaker-p (speaker)
  "Return non-nil if SPEAKER is a conversational turn (not a structural section)."
  (not (member (downcase speaker) '("references" "related"))))

(defun noesis--last-turn ()
  "Return (SPEAKER . HEADER-POS) for the last conversational turn, or nil.
Skips structural sections (References, Related)."
  (save-excursion
    (goto-char (point-max))
    (let (result)
      (while (and (not result)
                  (re-search-backward "^## \\(.+\\)$" nil t))
        (let ((spk (match-string-no-properties 1)))
          (when (noesis--turn-speaker-p spk)
            (setq result (cons spk (match-beginning 0))))))
      result)))

(defun noesis--structural-sections-start ()
  "Return the buffer position just before any trailing structural sections.
Structural sections (References, Related) must be at the end of the file.
Returns `point-max' if none are present."
  (save-excursion
    (goto-char (point-max))
    (let ((pos (point-max)))
      (while (re-search-backward "^## \\(.+\\)$" nil t)
        (if (not (noesis--turn-speaker-p (match-string-no-properties 1)))
            (setq pos (match-beginning 0))
          (goto-char (point-min))))  ; stop scanning
      pos)))

(defun noesis--prev-user-speaker ()
  "Return the speaker name from the most recent user (non-AI, non-structural) turn, or nil."
  (save-excursion
    (goto-char (point-max))
    (let (result)
      (while (and (not result)
                  (re-search-backward "^## \\(.+\\)$" nil t))
        (let ((spk (match-string-no-properties 1)))
          (when (and (noesis--turn-speaker-p spk)
                     (not (noesis--ai-speaker-p spk)))
            (setq result spk))))
      result)))

;;;###autoload
(defun noesis-goto-input ()
  "Navigate to the next input position in the transcript.

If the last turn is a user turn, move point to the end of its body.
If the last turn is an AI turn, append a new user-turn section using
the speaker name from the previous user turn, then place point on the
blank line that follows the new section header."
  (interactive)
  (let* ((last    (noesis--last-turn))
         (speaker (car last))
         (hdr-pos (cdr last)))
    (unless last
      (user-error "No turns found in buffer"))
    (if (not (noesis--ai-speaker-p speaker))
        ;; User turn — jump to the end of its body.
        (let ((body-end
               (save-excursion
                 (goto-char hdr-pos)
                 (forward-line 1)
                 (if (re-search-forward "^## " nil t)
                     (progn (beginning-of-line)
                            (skip-chars-backward " \t\n")
                            (point))
                   (goto-char (point-max))
                   (skip-chars-backward " \t\n")
                   (point)))))
          (goto-char body-end)
          (end-of-line))
      ;; AI turn — append a fresh user section and land on its body line.
      (let ((user-spk (or (noesis--prev-user-speaker)
                          (user-error "No previous user turn found"))))
        (let ((insert-pos (noesis--structural-sections-start)))
          (goto-char insert-pos)
          (skip-chars-backward "\n")
          (insert "\n\n## " user-spk "\n\n")
          (when (eobp)
            (forward-line -1)))))))

;; ── Auto-detection ───────────────────────────────────────────────────────────

(defun noesis--dated-slug-p (filename)
  "Return non-nil if FILENAME matches the NOESIS dated-slug convention.
Matches yyyy-mm-dd-*.md, yyyy-mm-dd-*.chat.md, etc."
  (string-match-p "\\`[0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}-[^/]+" filename))

;;;###autoload
(defun noesis-maybe-enable ()
  "Enable `noesis-mode' if the buffer's filename matches the NOESIS convention.
Add this to `find-file-hook' or `markdown-mode-hook'."
  (let ((name (file-name-nondirectory (or (buffer-file-name) ""))))
    (when (noesis--dated-slug-p name)
      (noesis-mode 1))))

;; ── Minor mode ───────────────────────────────────────────────────────────────

;;;###autoload
(define-minor-mode noesis-mode
  "Minor mode for NOESIS conversation transcript files.

Adds syntax highlighting for dates, section headers, reference lines,
and edit directives.  Provides commands to invoke the noesis CLI and
navigate between conversation turns.

Key bindings:
\\{noesis-mode-map}"
  :lighter " NOESIS"
  :keymap noesis-mode-map
  (if noesis-mode
      (progn
        (font-lock-add-keywords nil noesis--font-lock-keywords 'append)
        (auto-revert-mode 1))
    (font-lock-remove-keywords nil noesis--font-lock-keywords))
  (font-lock-flush))

(provide 'noesis)
;;; noesis.el ends here
