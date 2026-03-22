/**
 * nova-client.js — Клиентская библиотека Nova Chat
 * Управляет: аутентификацией, WebSocket-чатом, медиазагрузкой, WebRTC-звонками
 */

const Nova = (() => {
  // ─── Конфигурация ──────────────────────────────────────────
  const BASE_URL  = window.location.origin;
  const WS_BASE   = BASE_URL.replace(/^http/, 'ws');

  // ─── Состояние ─────────────────────────────────────────────
  let _token      = localStorage.getItem('nova_token') || null;
  let _me         = JSON.parse(localStorage.getItem('nova_me') || 'null');
  let _chatWS     = null;   // WebSocket чата
  let _callWS     = null;   // WebSocket сигнализации
  let _peerConn   = null;   // RTCPeerConnection
  let _localStream = null;  // MediaStream микрофона/камеры
  let _currentChatId = null;
  let _typingTimer  = null;
  const _handlers = {};     // event → [callbacks]

  // ─────────────────────────────────────────────────────────
  //  HTTP Helpers
  // ─────────────────────────────────────────────────────────
  async function _req(method, path, body = null, isForm = false) {
    const headers = {};
    if (_token) headers['Authorization'] = `Bearer ${_token}`;
    if (!isForm && body) headers['Content-Type'] = 'application/json';

    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: isForm ? body : (body ? JSON.stringify(body) : null),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Ошибка сервера');
    }
    return res.json();
  }

  const api = {
    get:    (path)        => _req('GET',    path),
    post:   (path, body)  => _req('POST',   path, body),
    patch:  (path, body)  => _req('PATCH',  path, body),
    delete: (path)        => _req('DELETE', path),
    upload: (path, form)  => _req('POST',   path, form, true),
  };

  // ─────────────────────────────────────────────────────────
  //  Event Emitter
  // ─────────────────────────────────────────────────────────
  function on(event, cb) {
    (_handlers[event] = _handlers[event] || []).push(cb);
  }

  function off(event, cb) {
    _handlers[event] = (_handlers[event] || []).filter(fn => fn !== cb);
  }

  function emit(event, data) {
    (_handlers[event] || []).forEach(fn => fn(data));
  }

  // ─────────────────────────────────────────────────────────
  //  Auth
  // ─────────────────────────────────────────────────────────
  async function register({ username, email, display_name, password }) {
    const res = await api.post('/api/auth/register', { username, email, display_name, password });
    _saveSession(res);
    return res;
  }

  async function login({ username, password }) {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(`${BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    });
    if (!res.ok) throw new Error('Неверный логин или пароль');
    const data = await res.json();
    _saveSession(data);
    return data;
  }

  async function logout() {
    await api.post('/api/auth/logout').catch(() => {});
    _token = null; _me = null;
    localStorage.removeItem('nova_token');
    localStorage.removeItem('nova_me');
    disconnectChat();
    emit('logout', null);
  }

  function _saveSession({ access_token, user }) {
    _token = access_token;
    _me    = user;
    localStorage.setItem('nova_token', _token);
    localStorage.setItem('nova_me', JSON.stringify(_me));
    emit('auth', _me);
  }

  function isLoggedIn() { return !!_token && !!_me; }
  function getMe()      { return _me; }

  // ─────────────────────────────────────────────────────────
  //  Chats
  // ─────────────────────────────────────────────────────────
  const chats = {
    list:          ()          => api.get('/api/chats/'),
    createPersonal:(targetId)  => api.post('/api/chats/personal', { target_user_id: targetId }),
    createGroup:   (data)      => api.post('/api/chats/group', data),
    members:       (chatId)    => api.get(`/api/chats/${chatId}/members`),
    addMember:     (chatId, uid) => api.post(`/api/chats/${chatId}/members/${uid}`),
  };

  // ─────────────────────────────────────────────────────────
  //  Messages (REST — история)
  // ─────────────────────────────────────────────────────────
  const messages = {
    history:  (chatId, beforeId = null) =>
      api.get(`/api/messages/${chatId}${beforeId ? `?before_id=${beforeId}` : ''}`),
    edit:     (msgId, text) => api.patch(`/api/messages/${msgId}?text=${encodeURIComponent(text)}`),
    delete:   (msgId)       => api.delete(`/api/messages/${msgId}`),
    markRead: (chatId, msgId) => api.post(`/api/messages/${chatId}/read/${msgId}`),
  };

  // ─────────────────────────────────────────────────────────
  //  Users
  // ─────────────────────────────────────────────────────────
  const users = {
    search:        (q)     => api.get(`/api/auth/users/search?q=${encodeURIComponent(q)}`),
    updateProfile: (data)  => api.patch('/api/auth/me', data),
    uploadAvatar:  (file)  => {
      const fd = new FormData();
      fd.append('file', file);
      return api.upload('/api/auth/me/avatar', fd);
    },
  };

  // ─────────────────────────────────────────────────────────
  //  Media Upload
  // ─────────────────────────────────────────────────────────
  const media = {
    /**
     * Загрузить файл и вернуть media_id для отправки в чат
     * @param {File} file
     * @returns {Promise<{id: number, file_path: string, mime_type: string}>}
     */
    upload(file) {
      const fd = new FormData();
      fd.append('file', file);

      const mime = file.type || '';
      let path = '/api/media/upload/file';
      if (mime.startsWith('image/'))       path = '/api/media/upload/image';
      else if (mime.startsWith('video/'))  path = '/api/media/upload/video';
      else if (mime.startsWith('audio/'))  path = '/api/media/upload/voice';

      return api.upload(path, fd);
    },
  };

  // ─────────────────────────────────────────────────────────
  //  WebSocket — Чат
  // ─────────────────────────────────────────────────────────
  function connectChat(chatId) {
    if (_chatWS && _currentChatId === chatId) return; // уже подключены
    disconnectChat();
    _currentChatId = chatId;

    const url = `${WS_BASE}/ws/chat/${chatId}?token=${_token}`;
    _chatWS = new WebSocket(url);

    _chatWS.onopen = () => {
      emit('ws_open', { chatId });
    };

    _chatWS.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        _handleServerEvent(data);
      } catch(e) { console.warn('[WS] parse error', e); }
    };

    _chatWS.onerror = (e) => emit('ws_error', e);

    _chatWS.onclose = (e) => {
      emit('ws_close', { chatId, code: e.code });
      // Авто-реконнект если не намеренное закрытие
      if (e.code !== 1000 && e.code !== 4001 && e.code !== 4003) {
        setTimeout(() => connectChat(chatId), 3000);
      }
    };
  }

  function disconnectChat() {
    if (_chatWS) {
      _chatWS.close(1000);
      _chatWS = null;
      _currentChatId = null;
    }
  }

  function _wsSend(payload) {
    if (_chatWS && _chatWS.readyState === WebSocket.OPEN) {
      _chatWS.send(JSON.stringify(payload));
    }
  }

  // ─── Отправка сообщений через WS ──────────────────────────
  function sendText(chatId, text, replyToId = null) {
    _wsSend({ type: 'chat_message', chat_id: chatId, text, reply_to: replyToId });
  }

  function sendMedia(chatId, mediaId, caption = '', replyToId = null) {
    _wsSend({ type: 'media_message', chat_id: chatId, media_id: mediaId, text: caption, reply_to: replyToId });
  }

  function sendTyping(chatId) {
    _wsSend({ type: 'typing', chat_id: chatId });
    clearTimeout(_typingTimer);
    _typingTimer = setTimeout(() => _wsSend({ type: 'stop_typing', chat_id: chatId }), 3000);
  }

  function sendRead(chatId, messageId) {
    _wsSend({ type: 'read', chat_id: chatId, message_id: messageId });
  }

  // ─── Обработка входящих WS-событий ───────────────────────
  function _handleServerEvent(data) {
    switch (data.type) {
      case 'new_message':
        emit('message', data.message);
        break;
      case 'user_typing':
        emit('typing', { chatId: data.chat_id, userId: data.user_id, name: data.display_name });
        break;
      case 'user_stop_typing':
        emit('stop_typing', { chatId: data.chat_id, userId: data.user_id });
        break;
      case 'message_read':
        emit('read', { chatId: data.chat_id, messageId: data.message_id, userId: data.user_id });
        break;
      case 'user_online':
        emit('user_online', { userId: data.user_id, name: data.display_name });
        break;
      case 'user_offline':
        emit('user_offline', { userId: data.user_id });
        break;
      case 'incoming_call':
        _handleIncomingCall(data);
        break;
      case 'call_accepted':
        emit('call_accepted', data);
        break;
      case 'call_rejected':
        emit('call_rejected', data);
        _cleanupCall();
        break;
      case 'call_ended':
        emit('call_ended', data);
        _cleanupCall();
        break;
      // WebRTC signals relayed back through chat WS
      case 'call_offer':
      case 'call_answer':
      case 'ice_candidate':
        _handleRtcSignal(data);
        break;
      default:
        emit('event', data);
    }
  }

  // ─────────────────────────────────────────────────────────
  //  WebRTC — Голосовые и видеозвонки
  // ─────────────────────────────────────────────────────────
  let _currentCallId   = null;
  let _iceServers      = [{ urls: 'stun:stun.l.google.com:19302' }];

  /**
   * Начать исходящий звонок
   * @param {number} chatId
   * @param {'voice'|'video'} type
   */
  async function startCall(chatId, type = 'voice') {
    const res = await api.post('/api/calls/start', { chat_id: chatId, type });
    _currentCallId = res.call_id;
    _iceServers    = res.ice_servers || _iceServers;

    // Получить медиапоток
    _localStream = await _getLocalStream(type === 'video');
    emit('local_stream', _localStream);

    // Создать PeerConnection и сделать offer
    await _createPeerConnection();
    const offer = await _peerConn.createOffer();
    await _peerConn.setLocalDescription(offer);

    // Отправить offer через WS
    _wsSend({ type: 'call_offer', call_id: _currentCallId, sdp: offer });
    emit('call_started', { callId: _currentCallId, direction: 'outgoing', callType: type });
    return _currentCallId;
  }

  /**
   * Принять входящий звонок
   * @param {number} callId
   * @param {RTCSessionDescriptionInit} offerSdp
   * @param {'voice'|'video'} callType
   */
  async function acceptCall(callId, offerSdp, callType = 'voice') {
    await api.post(`/api/calls/${callId}/accept`);
    _currentCallId = callId;

    _localStream = await _getLocalStream(callType === 'video');
    emit('local_stream', _localStream);

    await _createPeerConnection();
    await _peerConn.setRemoteDescription(new RTCSessionDescription(offerSdp));

    const answer = await _peerConn.createAnswer();
    await _peerConn.setLocalDescription(answer);
    _wsSend({ type: 'call_answer', call_id: callId, sdp: answer });
    emit('call_started', { callId, direction: 'incoming', callType });
  }

  async function rejectCall(callId) {
    await api.post(`/api/calls/${callId}/reject`).catch(() => {});
    emit('call_ended', { callId });
  }

  async function endCall() {
    if (!_currentCallId) return;
    await api.post(`/api/calls/${_currentCallId}/end`).catch(() => {});
    _cleanupCall();
  }

  function toggleMute(muted) {
    if (_localStream) {
      _localStream.getAudioTracks().forEach(t => t.enabled = !muted);
    }
  }

  function toggleCamera(enabled) {
    if (_localStream) {
      _localStream.getVideoTracks().forEach(t => t.enabled = enabled);
    }
  }

  async function _getLocalStream(withVideo = false) {
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
      video: withVideo,
    });
  }

  async function _createPeerConnection() {
    _peerConn = new RTCPeerConnection({ iceServers: _iceServers });

    // Добавить локальные треки
    if (_localStream) {
      _localStream.getTracks().forEach(track => _peerConn.addTrack(track, _localStream));
    }

    // Получить удалённые треки
    _peerConn.ontrack = (e) => {
      emit('remote_stream', e.streams[0]);
    };

    // Отправить ICE-кандидатов
    _peerConn.onicecandidate = (e) => {
      if (e.candidate) {
        _wsSend({
          type: 'ice_candidate',
          call_id: _currentCallId,
          candidate: e.candidate.toJSON(),
        });
      }
    };

    _peerConn.onconnectionstatechange = () => {
      emit('call_state', _peerConn.connectionState);
      if (['disconnected', 'failed', 'closed'].includes(_peerConn.connectionState)) {
        _cleanupCall();
      }
    };
  }

  async function _handleIncomingCall(data) {
    emit('incoming_call', {
      callId:   data.call_id,
      callType: data.call_type,
      caller:   data.caller,
      iceServers: data.ice_servers,
      // Пользователь должен вызвать acceptCall(callId, offerSdp)
      // после получения offer через WS
    });
    _currentCallId = data.call_id;
    _iceServers    = data.ice_servers || _iceServers;
  }

  async function _handleRtcSignal(data) {
    if (!_peerConn) return;
    try {
      if (data.type === 'call_offer') {
        await _peerConn.setRemoteDescription(new RTCSessionDescription(data.sdp));
        const answer = await _peerConn.createAnswer();
        await _peerConn.setLocalDescription(answer);
        _wsSend({ type: 'call_answer', call_id: data.call_id, sdp: answer });
      } else if (data.type === 'call_answer') {
        await _peerConn.setRemoteDescription(new RTCSessionDescription(data.sdp));
      } else if (data.type === 'ice_candidate') {
        await _peerConn.addIceCandidate(new RTCIceCandidate(data.candidate));
      }
    } catch(e) {
      console.error('[WebRTC]', e);
    }
  }

  function _cleanupCall() {
    if (_peerConn) { _peerConn.close(); _peerConn = null; }
    if (_localStream) { _localStream.getTracks().forEach(t => t.stop()); _localStream = null; }
    _currentCallId = null;
    emit('call_cleanup', null);
  }

  // ─────────────────────────────────────────────────────────
  //  Голосовые сообщения (запись в браузере)
  // ─────────────────────────────────────────────────────────
  let _mediaRecorder = null;
  let _audioChunks   = [];

  async function startVoiceRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    _mediaRecorder.ondataavailable = e => _audioChunks.push(e.data);
    _mediaRecorder.start();
    emit('recording_start', null);
  }

  async function stopVoiceRecording() {
    return new Promise((resolve) => {
      _mediaRecorder.onstop = async () => {
        const blob = new Blob(_audioChunks, { type: 'audio/webm' });
        const file = new File([blob], `voice_${Date.now()}.webm`, { type: 'audio/webm' });
        const uploaded = await media.upload(file);
        emit('recording_done', uploaded);
        // Остановить все треки
        _mediaRecorder.stream.getTracks().forEach(t => t.stop());
        resolve(uploaded);
      };
      _mediaRecorder.stop();
    });
  }

  function cancelVoiceRecording() {
    if (_mediaRecorder && _mediaRecorder.state !== 'inactive') {
      _mediaRecorder.stream.getTracks().forEach(t => t.stop());
      _mediaRecorder.stop();
      _audioChunks = [];
      emit('recording_cancelled', null);
    }
  }

  // ─────────────────────────────────────────────────────────
  //  Публичный API
  // ─────────────────────────────────────────────────────────
  return {
    // Auth
    register, login, logout, isLoggedIn, getMe,

    // Real-time
    connectChat, disconnectChat,
    sendText, sendMedia, sendTyping, sendRead,

    // REST
    chats, messages, users, media,

    // Calls (WebRTC)
    startCall, acceptCall, rejectCall, endCall,
    toggleMute, toggleCamera,

    // Voice recording
    startVoiceRecording, stopVoiceRecording, cancelVoiceRecording,

    // Events
    on, off,
  };
})();
