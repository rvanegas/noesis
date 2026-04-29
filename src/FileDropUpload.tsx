import './App.css'
import axios from 'axios'
import {useRef, useState} from 'react'

const VITE_API_BASE_URL = import.meta.env.VITE_API_BASE_URL

import type {FileType} from './types'

function FileDropUpload({newFileUploaded}: {
  newFileUploaded: (newFile: FileType) => void
}) {
  const [showDropZone, setShowDropZone] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleUpload = async (file: File) => {
    const url = VITE_API_BASE_URL + '/api/argument/upload'
    const formData = new FormData()
    formData.append('file', file)
    setIsUploading(true)
    setShowDropZone(false)
    try {
      const response = await axios.post(url, formData)
      const responseObject = JSON.parse(response.data.reply)
      newFileUploaded(responseObject)
    } catch (error) {
      console.error('Error: ', error)
    } finally {
      setIsUploading(false)
    }
  }

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const files = event.dataTransfer.files
    if (files.length > 0) handleUpload(files[0])
  }

  const onFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files && files.length > 0) handleUpload(files[0])
  }

  return (
    <div className="mt-4 w-full">
      <button
        onClick={() => setShowDropZone(prev => !prev)}
        className="px-4 py-2 ml-2 mt-2 mb-2 text-white bg-indigo-500 border-none rounded-xl flex items-center gap-2"
        disabled={isUploading}
      >
        Upload File
      </button>
      {isUploading && (
        <div className='mt-3'>
          <span className="ml-3 text-blue-600">Uploading...</span>
        </div>
      )}

      {showDropZone && (
        <div
          onDragOver={e => e.preventDefault()}
          onDrop={onDrop}
          className="py-4 px-10 mt-3 ml-2 mr-2 border-2 border-dashed border-gray-500 flex flex-col items-center justify-center">
          <div>Drop file here</div>
          <div>
            or{' '}
            <span
              onClick={() => fileInputRef.current?.click()}
              style={{textDecoration: 'underline', color: 'blue', cursor: 'pointer'}}>
              click to choose
            </span>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            style={{display: 'none'}}
            onChange={onFileSelect}
            disabled={isUploading}
          />
        </div>
      )}
    </div>
  )
}

export default FileDropUpload
