
Code	Details
422	
Error: Unprocessable Entity

Response body
Download
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": [
        "body",
        "student_id"
      ],
      "msg": "Input should be a valid integer, unable to parse string as an integer",
      "input": "21B-011-SE"
    }
  ]
}
Response headers
 access-control-allow-credentials: true 
 access-control-allow-origin: http://127.0.0.1:8000 
 content-length: 162 
 content-type: application/json 
 date: Thu,28 Nov 2024 15:03:44 GMT 
 server: uvicorn 
 vary: Origin 