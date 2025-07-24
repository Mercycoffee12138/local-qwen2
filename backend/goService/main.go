package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "mime/multipart"
    "net/http"
    "time"

    "github.com/google/uuid"
    "github.com/rs/cors"
)

// 修改结构体定义，支持多模态数据
type ChatRequest struct {
    BotType struct {
        Value string `json:"value"`
    } `json:"bot_type"`
    Messages       []interface{} `json:"messages"`
    MaxLength      int           `json:"max_length"`
    CurrentMessage interface{}   `json:"currentMessage"` // 改为 interface{} 支持复杂对象
    SystemPrompt   string        `json:"system_prompt"`
}

type ChatResponse struct {
    Response string `json:"response"`
    UserID   string `json:"user_id"`
}

// 添加上传响应结构体
type UploadResponse struct {
    Success  bool   `json:"success"`
    FileID   string `json:"file_id"`
    FileType string `json:"file_type"`
    FileData string `json:"file_data"`
    Mimetype string `json:"mimetype"`
    Error    string `json:"error,omitempty"`
}

func settingsHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method == http.MethodOptions {
        w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
        w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
        w.Header().Set("Access-Control-Allow-Credentials", "true")
        w.WriteHeader(http.StatusNoContent)
        return
    }

    // 转发到 Python 服务
    var requestBody []byte
    if r.Method == "POST" || r.Method == "PUT" {
        body, err := io.ReadAll(r.Body)
        if err != nil {
            http.Error(w, "Failed to read request body", http.StatusBadRequest)
            return
        }
        requestBody = body
    }

    url := "http://127.0.0.1:5001" + r.URL.Path
    req, err := http.NewRequest(r.Method, url, bytes.NewBuffer(requestBody))
    if err != nil {
        http.Error(w, "Failed to create request", http.StatusInternalServerError)
        return
    }

    // 复制请求头
    for key, values := range r.Header {
        for _, value := range values {
            req.Header.Add(key, value)
        }
    }

    client := &http.Client{Timeout: 30 * time.Second}
    resp, err := client.Do(req)
    if err != nil {
        http.Error(w, "Failed to forward request", http.StatusInternalServerError)
        return
    }
    defer resp.Body.Close()

    // 设置响应头
    w.Header().Set("Content-Type", "application/json")
    w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
    w.Header().Set("Access-Control-Allow-Credentials", "true")

    // 转发响应
    responseBody, err := io.ReadAll(resp.Body)
    if err != nil {
        http.Error(w, "Failed to read response", http.StatusInternalServerError)
        return
    }

    w.WriteHeader(resp.StatusCode)
    w.Write(responseBody)
}

// 新增：文件上传处理函数
func uploadHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method == http.MethodOptions {
        // 处理预检请求
        w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
        w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
        w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
        w.Header().Set("Access-Control-Allow-Credentials", "true")
        w.WriteHeader(http.StatusNoContent)
        return
    }

    // 设置响应头
    w.Header().Set("Content-Type", "application/json")
    w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
    w.Header().Set("Access-Control-Allow-Credentials", "true")

    // 解析multipart form
    err := r.ParseMultipartForm(32 << 20) // 32MB
    if err != nil {
        log.Printf("Failed to parse multipart form: %v", err)
        http.Error(w, "Failed to parse form", http.StatusBadRequest)
        return
    }

    // 创建新的multipart writer来转发请求
    var requestBody bytes.Buffer
    writer := multipart.NewWriter(&requestBody)

    // 获取上传的文件
    file, header, err := r.FormFile("file")
    if err != nil {
        log.Printf("Failed to get form file: %v", err)
        response := UploadResponse{
            Success: false,
            Error:   "No file uploaded",
        }
        json.NewEncoder(w).Encode(response)
        return
    }
    defer file.Close()

    // 将文件添加到新的multipart form中
    fileWriter, err := writer.CreateFormFile("file", header.Filename)
    if err != nil {
        log.Printf("Failed to create form file: %v", err)
        http.Error(w, "Failed to process file", http.StatusInternalServerError)
        return
    }

    // 复制文件内容
    _, err = io.Copy(fileWriter, file)
    if err != nil {
        log.Printf("Failed to copy file: %v", err)
        http.Error(w, "Failed to process file", http.StatusInternalServerError)
        return
    }

    // 关闭writer
    writer.Close()

    // 发送请求到Python服务
    url := "http://127.0.0.1:5001/upload"
    req, err := http.NewRequest("POST", url, &requestBody)
    if err != nil {
        log.Printf("Failed to create request: %v", err)
        http.Error(w, "Failed to forward request", http.StatusInternalServerError)
        return
    }

    // 设置Content-Type
    req.Header.Set("Content-Type", writer.FormDataContentType())

    client := &http.Client{
        Timeout: 30 * time.Second,
    }

    resp, err := client.Do(req)
    if err != nil {
        log.Printf("Failed to send request to Python server: %v", err)
        response := UploadResponse{
            Success: false,
            Error:   "Failed to upload file",
        }
        json.NewEncoder(w).Encode(response)
        return
    }
    defer resp.Body.Close()

    // 读取Python服务的响应
    responseBody, err := io.ReadAll(resp.Body)
    if err != nil {
        log.Printf("Failed to read response: %v", err)
        http.Error(w, "Failed to read response", http.StatusInternalServerError)
        return
    }

    // 直接转发Python服务的响应
    w.Header().Set("Content-Type", "application/json")
    w.Write(responseBody)
}

// 修改生成响应函数，直接传递完整的 currentMessage
func generateChatResponse(userID string, messages []interface{}, maxLength int, currentMessage interface{}, botType string, systemPrompt string) (string, error) {
    requestData := map[string]interface{}{
        "user_id":        userID,
        "messages":       messages,
        "max_length":     maxLength,
        "currentMessage": currentMessage, // 直接传递，不再包装
        "bot_type":       map[string]string{"value": botType},
        "system_prompt":  systemPrompt,
    }

    // 将请求数据编码为JSON
    requestBody, err := json.Marshal(requestData)
    if err != nil {
        return "", fmt.Errorf("failed to marshal request data: %v", err)
    }

    // 发送请求到Python服务
    url := "http://127.0.0.1:5001/chat"
    req, err := http.NewRequest("POST", url, bytes.NewBuffer(requestBody))
    if err != nil {
        return "", fmt.Errorf("failed to create request: %v", err)
    }
    req.Header.Set("Content-Type", "application/json")

    client := &http.Client{
        Timeout: 6000 * time.Second, // 增加超时时间到120秒
    }
    resp, err := client.Do(req)
    if err != nil {
        return "", fmt.Errorf("failed to send request to Python server: %v", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        return "", fmt.Errorf("received non-OK response from Python server: %d", resp.StatusCode)
    }

    // 读取响应数据
    var responseData map[string]interface{}
    if err := json.NewDecoder(resp.Body).Decode(&responseData); err != nil {
        return "", fmt.Errorf("failed to decode response data: %v", err)
    }

    responseText, ok := responseData["response"].(string)
    if !ok {
        return "", fmt.Errorf("response field missing or not a string")
    }

    return responseText, nil
}

func chatHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method == http.MethodOptions {
        // 处理预检请求
        w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
        w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
        w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
        w.Header().Set("Access-Control-Allow-Credentials", "true")
        w.WriteHeader(http.StatusNoContent)
        return
    }

    var chatRequest ChatRequest
    if err := json.NewDecoder(r.Body).Decode(&chatRequest); err != nil {
        log.Printf("Failed to parse request body: %v", err)
        http.Error(w, "Invalid request body", http.StatusBadRequest)
        return
    }

    // 设置响应头
    w.Header().Set("Content-Type", "application/json")
    w.Header().Set("Access-Control-Allow-Origin", r.Header.Get("Origin"))
    w.Header().Set("Access-Control-Allow-Credentials", "true")

    botType := chatRequest.BotType.Value
    messages := chatRequest.Messages
    maxLength := chatRequest.MaxLength
    if maxLength == 0 {
        maxLength = 8000
    }
    currentMessage := chatRequest.CurrentMessage // 直接使用，不再提取 Content
    systemPrompt := chatRequest.SystemPrompt
    log.Printf("收到的 system_prompt: %s", systemPrompt)

    userID, err := r.Cookie("user_id")
    if err != nil || userID.Value == "" {
        userID = &http.Cookie{
            Name:     "user_id",
            Value:    uuid.New().String(),
            HttpOnly: true,
            Secure:   false, // 本地开发设为 false
            SameSite: http.SameSiteLaxMode, // 改为 Lax
            Expires:  time.Now().Add(30 * 24 * time.Hour),
        }
        http.SetCookie(w, userID)
    }

    // 使用超时控制
    done := make(chan bool)
    var response string
    var responseErr error

    go func() {
        response, responseErr = generateChatResponse(userID.Value, messages, maxLength, currentMessage, botType, systemPrompt)
        done <- true
    }()

    select {
    case <-done:
        if responseErr != nil {
            log.Printf("Chat response generation failed: %v", responseErr)
            http.Error(w, "Failed to generate response", http.StatusInternalServerError)
            return
        }

        chatResponse := ChatResponse{
            Response: response,
            UserID:   userID.Value,
        }

        w.Header().Set("Content-Type", "application/json")
        if err := json.NewEncoder(w).Encode(chatResponse); err != nil {
            log.Printf("Failed to encode response: %v", err)
            http.Error(w, "Failed to encode response", http.StatusInternalServerError)
        }

    case <-time.After(6000 * time.Second): // 120秒超时
        log.Printf("Chat response generation timed out")
        http.Error(w, "Request timed out", http.StatusRequestTimeout)
    }
}

func main() {
    // 设置CORS
    corsHandler := cors.New(cors.Options{
        AllowedOrigins:   []string{"http://127.0.0.1:9100", "http://localhost:9100"},
        AllowCredentials: true,
        AllowedMethods:   []string{"POST", "OPTIONS"},
        AllowedHeaders:   []string{"Content-Type"},
    })

    // 注册路由处理器
    http.HandleFunc("/chat", chatHandler)
    http.HandleFunc("/upload", uploadHandler) // 新增上传处理器
    http.HandleFunc("/settings", settingsHandler)
    http.HandleFunc("/settings/", settingsHandler) // 处理子路径

    // 启动HTTP服务器
    server := &http.Server{
        Addr:    ":5002",
        Handler: corsHandler.Handler(http.DefaultServeMux),
    }

    log.Println("Starting server on port 5002...")
    log.Println("Available endpoints:")
    log.Println("  POST /chat - Chat endpoint")
    log.Println("  POST /upload - File upload endpoint")
    if err := server.ListenAndServe(); err != nil {
        log.Fatalf("Failed to start server: %v", err)
    }
}